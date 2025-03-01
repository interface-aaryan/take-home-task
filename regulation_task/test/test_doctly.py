import os
import doctly
from openai import OpenAI
import time

# Get Doctly API key from environment variables
doctly_api_key = os.getenv("DOCTLY_API_KEY")
if doctly_api_key:
    print("Found Doctly API key in environment")
else:
    print("Doctly API key not found")

# Get OpenAI API key from environment
openai_api_key = os.getenv("OPENAI_API_KEY")
if openai_api_key:
    print("Found OpenAI API key in environment")
else:
    print("OpenAI API key not found")

# Initialize the OpenAI client with your API key
openai_client = OpenAI(api_key=openai_api_key)
GPT_MODEL = "gpt-4"  # You can adjust this as needed

# Initialize the Doctly client with your API key
client = doctly.Client(doctly_api_key)

# Define file paths
pdf_file = '/Users/uday/Desktop/Desktop-Udays_MacBook_Pro/MSAI/interface-take-home/take-home-task/regulation_task/data/regulations/REG-ANSI A92.2.pdf'
output_md_filename = 'output-REG-ANSI-A92-2.md'
cleaned_md_filename = output_md_filename.replace(".md", "_cleaned.md")

# Function to split text into chunks of approximately max_tokens
def split_text_into_chunks(text, max_chars=6000):
    # Rough approximation: 1 token ≈ 4 characters for English text
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

# Function to process chunks with OpenAI and handle rate limits
def process_chunks_with_openai(chunks, meta_prompt):
    processed_chunks = []
    
    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i+1}/{len(chunks)} (size: {len(chunk)} chars)")
        
        retry_count = 0
        max_retries = 3
        success = False
        
        while not success and retry_count < max_retries:
            try:
                response = openai_client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=[
                        {"role": "system", "content": meta_prompt},
                        {"role": "user", "content": chunk}
                    ],
                    temperature=0,
                )
                
                processed_chunk = response.choices[0].message.content
                processed_chunks.append(processed_chunk)
                success = True
                
            except Exception as e:
                retry_count += 1
                if "rate_limit_exceeded" in str(e):
                    wait_time = 60 * (2 ** retry_count)  # Exponential backoff
                    print(f"Rate limit exceeded. Waiting {wait_time} seconds before retrying...")
                    time.sleep(wait_time)
                else:
                    print(f"Error processing chunk {i+1}: {e}")
                    if retry_count < max_retries:
                        print(f"Retrying in 5 seconds... (Attempt {retry_count+1}/{max_retries})")
                        time.sleep(5)
                    else:
                        print(f"Failed to process chunk after {max_retries} attempts.")
                        processed_chunks.append(chunk)  # Add original chunk to maintain document integrity
        
        # Add a small delay between chunks to avoid rate limits
        if i < len(chunks) - 1:
            time.sleep(2)
    
    return processed_chunks

try:
    # Check if the Markdown file already exists
    if not os.path.exists(output_md_filename):
        # Convert the PDF file to Markdown using Doctly
        markdown_content = client.to_markdown(pdf_file)
        
        # Save the Markdown content to a file
        with open(output_md_filename, 'w') as f:
            f.write(markdown_content)
        
        print(f"Conversion successful! Markdown file saved as '{output_md_filename}'")
    else:
        print(f"'{output_md_filename}' already exists. Skipping conversion.")
    
    # Meta prompt for polishing the markdown content
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
    
    # Read the Markdown file content
    with open(output_md_filename, 'r') as f:
        md_content = f.read()
    
    print(f"File size: {len(md_content)} characters")
    
    # Split content into manageable chunks
    chunks = split_text_into_chunks(md_content)
    print(f"Split content into {len(chunks)} chunks")
    
    # Process each chunk with OpenAI
    print("Processing chunks with OpenAI...")
    processed_chunks = process_chunks_with_openai(chunks, meta_prompt)
    
    # Combine processed chunks
    polished_md = "\n\n".join(processed_chunks)
    
    # Save the polished content
    with open(cleaned_md_filename, 'w') as f:
        f.write(polished_md)
    
    print(f"Polishing successful! Cleaned Markdown file saved as '{cleaned_md_filename}'")
    
except doctly.DoctlyError as e:
    print(f"An error occurred during conversion: {e}")
except Exception as e:
    print(f"An error occurred: {e}")