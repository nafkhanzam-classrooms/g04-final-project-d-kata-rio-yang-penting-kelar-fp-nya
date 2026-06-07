import os
import json
import time
import requests
from markdownify import markdownify as md

QUESTIONS_DIR = 'data/questions'

def fetch_description(title_slug):
    url = f"https://alfa-leetcode-api.onrender.com/select?titleSlug={title_slug}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'question' in data:
                return md(data['question'])
    except Exception as e:
        print(f"Error fetching {title_slug}: {e}")
    return None

def main():
    for root, dirs, files in os.walk(QUESTIONS_DIR):
        if 'metadata.json' in files and 'description.md' in files:
            with open(os.path.join(root, 'metadata.json'), 'r') as f:
                metadata = json.load(f)
            
            title_slug = metadata.get('id')
            if not title_slug:
                continue
            
            desc_path = os.path.join(root, 'description.md')
            with open(desc_path, 'r') as f:
                content = f.read()
            
            if 'Problem description goes here...' in content:
                print(f"Fetching description for {title_slug}...")
                new_desc = fetch_description(title_slug)
                if new_desc:
                    # Replace the placeholder with the actual description
                    new_content = content.replace('Problem description goes here...', new_desc.strip())
                    with open(desc_path, 'w') as f:
                        f.write(new_content)
                    print(f"Successfully updated {title_slug}")
                else:
                    print(f"Failed to fetch description for {title_slug}")
                
                # Sleep to avoid rate limiting
                time.sleep(1.5)

if __name__ == '__main__':
    main()
