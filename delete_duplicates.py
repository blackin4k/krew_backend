import boto3
import os
import csv
import sys
import io

# Force UTF-8 for stdout (especially needed on Windows when redirecting)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# R2 Configuration
ENDPOINT_URL = "https://ced7d2775d362f5eee444f2ec74bd7fd.r2.cloudflarestorage.com"
ACCESS_KEY_ID = "0022f6249cf59fb8f55da24eea22cbd2"
SECRET_ACCESS_KEY = "a8b8964edaa3693bd66bc35fd2296510c55260c17acab030b6ffdbe49b375c28"
BUCKET_NAME = "krew-music"

DUPLICATES_FILE = r"..\dupicates.txt"

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY_ID,
        aws_secret_access_key=SECRET_ACCESS_KEY
    )

def parse_duplicates(filepath):
    """
    Parses the duplicates file.
    Expected format: ID \t "Title" \t "Artist" \t "Filename"
    Returns a dictionary: { (Title, Artist): [list of filenames] }
    """
    groups = {}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        # It's a tab separated file but with quotes around fields sometimes?
        # Let's inspect the lines manually first to be safe, or use csv with \t delimiter
        reader = csv.reader(f, delimiter='\t')
        
        for row in reader:
            if not row or len(row) < 4:
                continue
            
            # Row structure: [ID, Title, Artist, Filename]
            # Remove quotes if present
            title = row[1].strip('"')
            artist = row[2].strip('"')
            filename = row[3].strip('"')
            
            key = (title, artist)
            if key not in groups:
                groups[key] = []
            groups[key].append(filename)
            
    return groups

def main():
    dry_run = "--delete" not in sys.argv
    
    print(f"Reading duplicates from {DUPLICATES_FILE}...")
    try:
        groups = parse_duplicates(DUPLICATES_FILE)
    except FileNotFoundError:
        print(f"Error: File not found at {DUPLICATES_FILE}")
        return

    print(f"Found {len(groups)} unique songs with potential duplicates.")
    
    files_to_delete = []
    files_to_keep_count = 0
    
    with open("deletion_log.txt", "w", encoding="utf-8") as log_file:
        for (title, artist), filenames in groups.items():
            if len(filenames) < 2:
                continue
                
            sorted_files = sorted(filenames, key=len)
            
            keep = sorted_files[0]
            discard = sorted_files[1:]
            
            files_to_keep_count += 1
            for f in discard:
                files_to_delete.append(f)
                log_file.write(f"MATCH: {title} - {artist}\n")
                log_file.write(f"  KEEP:   {keep}\n")
                log_file.write(f"  DELETE: {f}\n")
                log_file.write("-" * 20 + "\n")

        log_file.write(f"\nSummary:\n")
        log_file.write(f"  Sets of duplicates processed: {files_to_keep_count}\n")
        log_file.write(f"  Files marked for deletion: {len(files_to_delete)}\n")
        
        if dry_run:
            log_file.write("\n[DRY RUN] No files were deleted. Run with --delete to execute.\n")
    
    # Print summary to stdout as well (safe characters)
    print(f"Summary generated in deletion_log.txt")
    print(f"Sets of duplicates processed: {files_to_keep_count}")
    print(f"Files marked for deletion: {len(files_to_delete)}")
    
    if not dry_run:

        print("\n[EXECUTION] Deleting files from R2...")
        s3 = get_s3_client()
        
        # Batch delete if possible, or one by one
        # Boto3 delete_objects can take up to 1000 keys
        
        # let's do chunks of 1000
        chunk_size = 1000
        for i in range(0, len(files_to_delete), chunk_size):
            chunk = files_to_delete[i:i+chunk_size]
            objects = [{'Key': f} for f in chunk]
            
            response = s3.delete_objects(
                Bucket=BUCKET_NAME,
                Delete={'Objects': objects}
            )
            
            if 'Deleted' in response:
                print(f"  Deleted {len(response['Deleted'])} files.")
            if 'Errors' in response:
                print(f"  Errors encountered: {response['Errors']}")

if __name__ == "__main__":
    main()
