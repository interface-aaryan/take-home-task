import os
import doctly
import time
import glob
from pathlib import Path
import asyncio
import aiofiles
from typing import List, Dict, Any, Tuple
import sys
from concurrent.futures import ThreadPoolExecutor
import threading

# Add the parent directory to the sys.path to import from regulatory_compliance_processor
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
sys.path.append(str(parent_dir))

# Get OpenAI API key from environment
openai_api_key = os.getenv("OPENAI_API_KEY")
if openai_api_key:
    print("Found OpenAI API key in environment")
else:
    print("OpenAI API key not found in environment")
    sys.exit(1)

from regulatory_compliance_processor.config import GPT_MODEL, openai_client

# Get Doctly API key from environment variables
doctly_api_key = os.getenv("DOCTLY_API_KEY")
if doctly_api_key:
    print("Found Doctly API key in environment")
else:
    print("Doctly API key not found")
    sys.exit(1)

# Initialize the Doctly client with your API key
doctly_client = doctly.Client(doctly_api_key)

# Define directories - use relative paths from the test directory
REGULATIONS_DIR = os.path.join(parent_dir, "data/regulations")
RAW_MD_DIR = os.path.join(REGULATIONS_DIR, "raw_md")
POLISHED_MD_DIR = os.path.join(REGULATIONS_DIR, "polished")

print(f"Regulations directory: {REGULATIONS_DIR}")
print(f"Raw MD directory: {RAW_MD_DIR}")
print(f"Polished MD directory: {POLISHED_MD_DIR}")

# Create output directories if they don't exist
os.makedirs(RAW_MD_DIR, exist_ok=True)
os.makedirs(POLISHED_MD_DIR, exist_ok=True)

# Locks for thread-safe printing and API access
print_lock = threading.Lock()
doctly_lock = threading.Lock()
openai_lock = threading.Lock()

# Function to safely print with a lock
def safe_print(message):
    with print_lock:
        print(message)

# Function to split text into chunks of approximately max_tokens
def split_text_into_chunks(text, max_chars=6000):
    chunks = []
    current_chunk = ""
    
    # Try to split at paragraph boundaries
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) + 2 <= max_chars:  # +2 for the newlines
            current_chunk += paragraph + '\n\n'
        else:
            # If the current chunk is not empty, add it to chunks
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            # Start a new chunk with the current paragraph
            current_chunk = paragraph + '\n\n'
    
    # Add the last chunk if it's not empty
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

# These functions are no longer needed as the logic is now in the main function's
# process_with_semaphores local function
# (Keeping them commented out for reference)

# Function to process a single chunk with OpenAI (synchronous)
# def process_chunk_with_openai(chunk, meta_prompt, chunk_index, total_chunks, file_id):
#     # This function has been replaced by inline code in process_with_semaphores
#     pass

# Function to process multiple chunks with OpenAI in parallel
# def process_chunks_with_openai(chunks, meta_prompt, file_id):
#     # This function has been replaced by inline code in process_with_semaphores
#     pass

# Function to convert PDF to markdown using Doctly
def convert_pdf_to_markdown(pdf_path, raw_md_path, file_id):
    with doctly_lock:  # Use lock to prevent too many simultaneous Doctly requests
        try:
            safe_print(f"[{file_id}] Converting to Markdown...")
            markdown_content = doctly_client.to_markdown(pdf_path)
            
            # Save the markdown content
            with open(raw_md_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            
            safe_print(f"[{file_id}] Conversion successful! Saved as '{raw_md_path}'")
            return markdown_content
        except Exception as e:
            safe_print(f"[{file_id}] Doctly conversion error: {e}")
            raise e

# Function to read markdown file
def read_markdown_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

# Function to save polished markdown file
def save_polished_markdown(file_path, content):
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

# Function to process a single PDF file - this is the main processing pipeline for each file
def process_single_file(pdf_path, file_index, total_files):
    # Get just the filename without directory or extension
    filename = os.path.basename(pdf_path)
    base_filename = os.path.splitext(filename)[0]
    file_id = f"File {file_index+1}/{total_files} ({base_filename})"
    
    # Define output paths for raw and polished markdown
    raw_md_path = os.path.join(RAW_MD_DIR, f"{base_filename}.md")
    polished_md_path = os.path.join(POLISHED_MD_DIR, f"{base_filename}.md")
    
    try:
        # Check if the polished Markdown file already exists (full idempotence check)
        if os.path.exists(polished_md_path):
            safe_print(f"[{file_id}] '{polished_md_path}' already exists. Skipping processing.")
            return True
        
        # Get or create raw markdown content
        if os.path.exists(raw_md_path):
            safe_print(f"[{file_id}] Raw markdown exists. Reading from file.")
            markdown_content = read_markdown_file(raw_md_path)
        else:
            try:
                # Convert PDF to markdown using Doctly
                markdown_content = convert_pdf_to_markdown(pdf_path, raw_md_path, file_id)
            except Exception as e:
                safe_print(f"[{file_id}] Could not convert PDF to markdown: {e}")
                return False
        
        # Process the markdown with OpenAI
        meta_prompt = """
You are an expert in document formatting and text processing. Your task is to clean and standardize a Markdown (.md) file while preserving its structure and readability. Follow these guidelines:
- Fix Paragraph Continuity: Ensure that paragraphs are correctly joined if they are broken across lines or pages.
- Standardize Formatting: Use proper Markdown syntax for section headers, subheadings, and bullet points.
- Maintain Proper Indentation: Ensure hierarchical sections (headings, subheadings, lists) are properly indented and structured.
- Apply Markdown Syntax: Use # for headings, **bold** for emphasis, and - or * for unordered lists where appropriate.
- Remove Pagination Artifacts: Strip out any leftover page numbers, headers, or footers that do not belong in the content.
- Fix Multi-Page Clauses: If a clause is split across multiple pages, merge it properly so it reads fluidly.
- Preserve Legal Numbering: If the document contains numbered regulations or sections, ensure their structure and sequence remain intact.
- Enhance Readability: Ensure the final output is well-formatted, easy to read, and retains all the original information without unnecessary clutter.

Note: You will receive this document in chunks. Process each chunk independently and focus on cleaning the formatting while maintaining the content structure.
"""
        
        safe_print(f"[{file_id}] File size: {len(markdown_content)} characters")
        
        # Split content into manageable chunks
        chunks = split_text_into_chunks(markdown_content)
        safe_print(f"[{file_id}] Split into {len(chunks)} chunks")
        
        # Process chunks with OpenAI
        processed_chunks = process_chunks_with_openai(chunks, meta_prompt, file_id)
        
        # Combine processed chunks
        polished_md = "\n\n".join(processed_chunks)
        
        # Save the polished content
        save_polished_markdown(polished_md_path, polished_md)
        
        safe_print(f"[{file_id}] Polishing successful! Saved as '{polished_md_path}'")
        return True
        
    except Exception as e:
        safe_print(f"[{file_id}] Error: {e}")
        return False

# Main function to coordinate processing of all PDF files
def main():
    print(f"Using OpenAI model: {GPT_MODEL}")
    
    # Get all PDF files in the regulations directory
    pdf_files = glob.glob(os.path.join(REGULATIONS_DIR, "*.pdf"))
    
    if not pdf_files:
        print(f"No PDF files found in {REGULATIONS_DIR}")
        return
    
    print(f"Found {len(pdf_files)} PDF files to process")
    
    # Initialize counters and state
    total_files = len(pdf_files)
    processed_count = 0
    results = []
    
    # Initialize API semaphores - only ONE call to each API at a time
    doctly_semaphore = threading.Semaphore(1)  # Only 1 Doctly call at a time
    openai_semaphore = threading.Semaphore(1)  # Only 1 OpenAI call at a time
    
    # Define a modified process function that uses the shared semaphores
    def process_with_semaphores(pdf_path, file_index):
        # Get just the filename without directory or extension
        filename = os.path.basename(pdf_path)
        base_filename = os.path.splitext(filename)[0]
        file_id = f"File {file_index+1}/{total_files} ({base_filename})"
        
        # Define output paths for raw and polished markdown
        raw_md_path = os.path.join(RAW_MD_DIR, f"{base_filename}.md")
        polished_md_path = os.path.join(POLISHED_MD_DIR, f"{base_filename}.md")
        
        try:
            # Check if the polished Markdown file already exists (full idempotence check)
            if os.path.exists(polished_md_path):
                safe_print(f"[{file_id}] '{polished_md_path}' already exists. Skipping processing.")
                return True
            
            # Get or create raw markdown content
            if os.path.exists(raw_md_path):
                safe_print(f"[{file_id}] Raw markdown exists. Reading from file.")
                markdown_content = read_markdown_file(raw_md_path)
            else:
                try:
                    # Convert PDF to markdown using Doctly - with semaphore
                    safe_print(f"[{file_id}] Waiting for Doctly access...")
                    with doctly_semaphore:
                        safe_print(f"[{file_id}] Converting to Markdown with Doctly...")
                        markdown_content = doctly_client.to_markdown(pdf_path)
                        
                        # Save the markdown content
                        with open(raw_md_path, 'w', encoding='utf-8') as f:
                            f.write(markdown_content)
                        
                        safe_print(f"[{file_id}] Conversion successful! Saved as '{raw_md_path}'")
                except Exception as e:
                    safe_print(f"[{file_id}] Could not convert PDF to markdown: {e}")
                    return False
            
            # Process the markdown with OpenAI
            meta_prompt = """
You are an expert in document formatting and text processing. Your task is to clean and standardize a Markdown (.md) file while preserving its structure and readability. Follow these guidelines:
- Fix Paragraph Continuity: Ensure that paragraphs are correctly joined if they are broken across lines or pages.
- Standardize Formatting: Use proper Markdown syntax for section headers, subheadings, and bullet points.
- Maintain Proper Indentation: Ensure hierarchical sections (headings, subheadings, lists) are properly indented and structured.
- Apply Markdown Syntax: Use # for headings, **bold** for emphasis, and - or * for unordered lists where appropriate.
- Remove Pagination Artifacts: Strip out any leftover page numbers, headers, or footers that do not belong in the content.
- Fix Multi-Page Clauses: If a clause is split across multiple pages, merge it properly so it reads fluidly.
- Preserve Legal Numbering: If the document contains numbered regulations or sections, ensure their structure and sequence remain intact.
- Enhance Readability: Ensure the final output is well-formatted, easy to read, and retains all the original information without unnecessary clutter.

Note: You will receive this document in chunks. Process each chunk independently and focus on cleaning the formatting while maintaining the content structure.
"""
            
            safe_print(f"[{file_id}] File size: {len(markdown_content)} characters")
            
            # Split content into manageable chunks
            chunks = split_text_into_chunks(markdown_content)
            safe_print(f"[{file_id}] Split into {len(chunks)} chunks")
            
            # Process chunks with OpenAI one at a time - with semaphore
            processed_chunks = []
            for i, chunk in enumerate(chunks):
                safe_print(f"[{file_id}] Waiting for OpenAI access for chunk {i+1}/{len(chunks)}...")
                with openai_semaphore:
                    safe_print(f"[{file_id}] Processing chunk {i+1}/{len(chunks)} (size: {len(chunk)} chars)")
                    retry_count = 0
                    max_retries = 3
                    
                    while retry_count < max_retries:
                        try:
                            response = openai_client.chat.completions.create(
                                model=GPT_MODEL,
                                messages=[
                                    {"role": "system", "content": meta_prompt},
                                    {"role": "user", "content": chunk}
                                ],
                                temperature=0,
                            )
                            
                            processed_chunks.append(response.choices[0].message.content)
                            break
                                
                        except Exception as e:
                            retry_count += 1
                            safe_print(f"[{file_id}] Error processing chunk {i+1}: {str(e)}")
                            
                            if "rate_limit_exceeded" in str(e):
                                wait_time = 20 * (2 ** retry_count)  # Exponential backoff
                                safe_print(f"[{file_id}] Rate limit exceeded. Waiting {wait_time} seconds before retrying...")
                                time.sleep(wait_time)
                            else:
                                time.sleep(5)
                                safe_print(f"[{file_id}] Retrying... (Attempt {retry_count+1}/{max_retries})")
                                
                            if retry_count >= max_retries:
                                safe_print(f"[{file_id}] Failed to process chunk after {max_retries} attempts. Using original content.")
                                processed_chunks.append(chunk)  # Use original chunk on failure
            
            # Combine processed chunks
            polished_md = "\n\n".join(processed_chunks)
            
            # Save the polished content
            save_polished_markdown(polished_md_path, polished_md)
            
            safe_print(f"[{file_id}] Polishing successful! Saved as '{polished_md_path}'")
            return True
                
        except Exception as e:
            safe_print(f"[{file_id}] Error: {e}")
            return False
    
    # Process multiple files in parallel with ThreadPoolExecutor
    # Each thread will coordinate API access using the semaphores
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_file = {
            executor.submit(process_with_semaphores, pdf_file, i): i 
            for i, pdf_file in enumerate(pdf_files)
        }
        
        # Wait for all tasks to complete
        for future in future_to_file:
            result = future.result()
            results.append(result)
    
    # Count successful operations
    successfully_processed = sum(1 for result in results if result)
    
    print(f"\nProcessing complete. Successfully processed {successfully_processed}/{len(pdf_files)} files.")
    print(f"Raw markdown files saved to: {RAW_MD_DIR}")
    print(f"Polished markdown files saved to: {POLISHED_MD_DIR}")

if __name__ == "__main__":
    # Run the main function
    main()