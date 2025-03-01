import os
import doctly
import time
import glob
from pathlib import Path
import asyncio
import aiofiles
from typing import List, Dict, Any, Tuple
import sys

# Add the parent directory to the sys.path to import from regulatory_compliance_processor
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
sys.path.append(str(parent_dir))

# Import OpenAI client and model from config
from regulatory_compliance_processor.config import openai_client, GPT_MODEL

# Convert sync client to async client
from openai import AsyncOpenAI
async_openai_client = AsyncOpenAI(api_key=openai_client.api_key)

# Get Doctly API key from environment variables
doctly_api_key = os.getenv("DOCTLY_API_KEY")
if doctly_api_key:
    print("Found Doctly API key in environment")
else:
    print("Doctly API key not found")

# Initialize the Doctly client with your API key
client = doctly.Client(doctly_api_key)

# Define directories
REGULATIONS_DIR = "../data/regulations"
RAW_MD_DIR = f"{REGULATIONS_DIR}/raw_md"
POLISHED_MD_DIR = f"{REGULATIONS_DIR}/polished"

# Create output directories if they don't exist
os.makedirs(RAW_MD_DIR, exist_ok=True)
os.makedirs(POLISHED_MD_DIR, exist_ok=True)

# For tracking concurrent API calls
doctly_semaphore = asyncio.Semaphore(2)  # Limit to 2 concurrent Doctly calls
openai_semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent OpenAI calls

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

# Function to process a single chunk with OpenAI
async def process_chunk_with_openai(chunk: str, meta_prompt: str, chunk_index: int, total_chunks: int, file_id: str) -> str:
    print(f"[{file_id}] Processing chunk {chunk_index+1}/{total_chunks} (size: {len(chunk)} chars)")
    
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            async with openai_semaphore:
                # Uses the imported GPT_MODEL from config
                response = await openai_client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=[
                        {"role": "system", "content": meta_prompt},
                        {"role": "user", "content": chunk}
                    ],
                    temperature=0,
                )
                
                return response.choices[0].message.content
                
        except Exception as e:
            retry_count += 1
            if "rate_limit_exceeded" in str(e):
                wait_time = 20 * (2 ** retry_count)  # Exponential backoff
                print(f"[{file_id}] Rate limit exceeded. Waiting {wait_time} seconds before retrying...")
                await asyncio.sleep(wait_time)
            else:
                print(f"[{file_id}] Error processing chunk {chunk_index+1}: {e}")
                if retry_count < max_retries:
                    await asyncio.sleep(5)
                    print(f"[{file_id}] Retrying... (Attempt {retry_count+1}/{max_retries})")
                else:
                    print(f"[{file_id}] Failed to process chunk after {max_retries} attempts. Using original content.")
                    return chunk  # Return original chunk on failure
    
    return chunk  # Return original chunk if all retries failed

# Function to process multiple chunks with OpenAI in parallel
async def process_chunks_with_openai(chunks: List[str], meta_prompt: str, file_id: str) -> List[str]:
    # Process chunks concurrently with limited concurrency
    tasks = []
    for i, chunk in enumerate(chunks):
        tasks.append(process_chunk_with_openai(chunk, meta_prompt, i, len(chunks), file_id))
    
    # Wait for all chunks to be processed
    processed_chunks = await asyncio.gather(*tasks)
    return processed_chunks

# Function to convert PDF to markdown using Doctly
async def convert_pdf_to_markdown(pdf_path: str, raw_md_path: str, file_id: str) -> str:
    # Run the synchronous Doctly conversion in a thread pool to avoid blocking
    def doctly_convert():
        try:
            print(f"[{file_id}] Converting to Markdown...")
            return client.to_markdown(pdf_path)
        except Exception as e:
            print(f"[{file_id}] Doctly conversion error: {e}")
            raise e
    
    # Use semaphore to limit concurrent Doctly calls
    async with doctly_semaphore:
        # Run the conversion in a separate thread pool
        markdown_content = await asyncio.to_thread(doctly_convert)
        
        # Save the markdown content
        async with aiofiles.open(raw_md_path, 'w', encoding='utf-8') as f:
            await f.write(markdown_content)
        
        print(f"[{file_id}] Conversion successful! Saved as '{raw_md_path}'")
        return markdown_content

# Function to read markdown file
async def read_markdown_file(file_path: str) -> str:
    async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
        return await f.read()

# Function to save polished markdown file
async def save_polished_markdown(file_path: str, content: str) -> None:
    async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
        await f.write(content)

# Function to process a single PDF file
async def process_pdf_file(pdf_path: str, file_index: int, total_files: int) -> bool:
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
            print(f"[{file_id}] '{polished_md_path}' already exists. Skipping processing.")
            return True
        
        # Get or create raw markdown content
        if os.path.exists(raw_md_path):
            print(f"[{file_id}] Raw markdown exists. Reading from file.")
            markdown_content = await read_markdown_file(raw_md_path)
        else:
            # Convert PDF to markdown
            markdown_content = await convert_pdf_to_markdown(pdf_path, raw_md_path, file_id)
        
        # Meta prompt for polishing
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
        
        print(f"[{file_id}] File size: {len(markdown_content)} characters")
        
        # Split content into manageable chunks
        chunks = split_text_into_chunks(markdown_content)
        print(f"[{file_id}] Split into {len(chunks)} chunks")
        
        # Process chunks concurrently
        processed_chunks = await process_chunks_with_openai(chunks, meta_prompt, file_id)
        
        # Combine processed chunks
        polished_md = "\n\n".join(processed_chunks)
        
        # Save the polished content
        await save_polished_markdown(polished_md_path, polished_md)
        
        print(f"[{file_id}] Polishing successful! Saved as '{polished_md_path}'")
        return True
        
    except Exception as e:
        print(f"[{file_id}] Error: {e}")
        return False

# Main function to process all PDF files
async def main():
    print(f"Using OpenAI model: {GPT_MODEL}")
    
    # Get all PDF files in the regulations directory
    pdf_files = glob.glob(os.path.join(REGULATIONS_DIR, "*.pdf"))
    
    if not pdf_files:
        print(f"No PDF files found in {REGULATIONS_DIR}")
        return
    
    print(f"Found {len(pdf_files)} PDF files to process")
    
    # Process files concurrently (but with controlled concurrency)
    tasks = []
    for i, pdf_file in enumerate(pdf_files):
        tasks.append(process_pdf_file(pdf_file, i, len(pdf_files)))
    
    # Wait for all files to be processed and track results
    results = await asyncio.gather(*tasks)
    
    # Count successful operations
    successfully_processed = sum(1 for result in results if result)
    
    print(f"\nProcessing complete. Successfully processed {successfully_processed}/{len(pdf_files)} files.")
    print(f"Raw markdown files saved to: {RAW_MD_DIR}")
    print(f"Polished markdown files saved to: {POLISHED_MD_DIR}")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())