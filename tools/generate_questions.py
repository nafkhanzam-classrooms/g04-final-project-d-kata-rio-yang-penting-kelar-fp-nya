import os
import re
import json

# Path to the downloaded gist
GIST_PATH = "/home/seannicholasdavidson/.gemini/antigravity-ide/brain/354681be-517a-4ec5-b562-31d43c6554f2/.system_generated/steps/77/content.md"

# Output directory
OUT_DIR = "data/questions"

# Rough difficulty mapping based on standard LeetCode levels
DIFFICULTIES = {
    "Two Sum": "easy",
    "Best Time to Buy and Sell Stock": "easy",
    "Contains Duplicate": "easy",
    "Product of Array Except Self": "medium",
    "Maximum Subarray": "medium",
    "Maximum Product Subarray": "medium",
    "Find Minimum in Rotated Sorted Array": "medium",
    "Search in Rotated Sorted Array": "medium",
    "3Sum": "medium",
    "Container With Most Water": "medium",
    "Sum of Two Integers": "medium",
    "Number of 1 Bits": "easy",
    "Counting Bits": "easy",
    "Missing Number": "easy",
    "Reverse Bits": "easy",
    "Climbing Stairs": "easy",
    "Coin Change": "medium",
    "Longest Increasing Subsequence": "medium",
    "Longest Common Subsequence": "medium",
    "Word Break Problem": "medium",
    "Combination Sum": "medium",
    "House Robber": "medium",
    "House Robber II": "medium",
    "Decode Ways": "medium",
    "Unique Paths": "medium",
    "Jump Game": "medium",
    "Clone Graph": "medium",
    "Course Schedule": "medium",
    "Pacific Atlantic Water Flow": "medium",
    "Number of Islands": "medium",
    "Longest Consecutive Sequence": "medium",
    "Alien Dictionary (Leetcode Premium)": "hard",
    "Graph Valid Tree (Leetcode Premium)": "medium",
    "Number of Connected Components in an Undirected Graph (Leetcode Premium)": "medium",
    "Insert Interval": "medium",
    "Merge Intervals": "medium",
    "Non-overlapping Intervals": "medium",
    "Meeting Rooms (Leetcode Premium)": "easy",
    "Meeting Rooms II (Leetcode Premium)": "medium",
    "Reverse a Linked List": "easy",
    "Detect Cycle in a Linked List": "easy",
    "Merge Two Sorted Lists": "easy",
    "Merge K Sorted Lists": "hard",
    "Remove Nth Node From End Of List": "medium",
    "Reorder List": "medium",
    "Set Matrix Zeroes": "medium",
    "Spiral Matrix": "medium",
    "Rotate Image": "medium",
    "Word Search": "medium",
    "Longest Substring Without Repeating Characters": "medium",
    "Longest Repeating Character Replacement": "medium",
    "Minimum Window Substring": "hard",
    "Valid Anagram": "easy",
    "Group Anagrams": "medium",
    "Valid Parentheses": "easy",
    "Valid Palindrome": "easy",
    "Longest Palindromic Substring": "medium",
    "Palindromic Substrings": "medium",
    "Encode and Decode Strings (Leetcode Premium)": "medium",
    "Maximum Depth of Binary Tree": "easy",
    "Same Tree": "easy",
    "Invert/Flip Binary Tree": "easy",
    "Binary Tree Maximum Path Sum": "hard",
    "Binary Tree Level Order Traversal": "medium",
    "Serialize and Deserialize Binary Tree": "hard",
    "Subtree of Another Tree": "easy",
    "Construct Binary Tree from Preorder and Inorder Traversal": "medium",
    "Validate Binary Search Tree": "medium",
    "Kth Smallest Element in a BST": "medium",
    "Lowest Common Ancestor of BST": "medium",
    "Implement Trie (Prefix Tree)": "medium",
    "Add and Search Word": "medium",
    "Word Search II": "hard",
    "Top K Frequent Elements": "medium",
    "Find Median from Data Stream": "hard"
}

def clean_title(title):
    # Remove (Leetcode Premium) suffix for ID generation
    t = title.replace("(Leetcode Premium)", "").strip()
    # Create a slug
    return re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')

def main():
    if not os.path.exists(GIST_PATH):
        print("Gist file not found at", GIST_PATH)
        return
        
    with open(GIST_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    current_category = "Uncategorized"
    
    for line in lines:
        line = line.strip()
        # Check for category header (e.g., ## Array)
        cat_match = re.match(r'^##\s+(.+)$', line)
        if cat_match:
            current_category = cat_match.group(1).strip()
            continue
            
        # Check for question (e.g., - [x] [Two Sum](https://...))
        # Or - [ ] [Title](url)
        q_match = re.match(r'^\-\s+\[[x\s]\]\s+\[([^\]]+)\]\(([^)]+)\)', line)
        if q_match:
            title = q_match.group(1).strip()
            url = q_match.group(2).strip()
            difficulty = DIFFICULTIES.get(title, "medium")
            
            slug = clean_title(title)
            
            # Create directories
            q_dir = os.path.join(OUT_DIR, difficulty, slug)
            os.makedirs(q_dir, exist_ok=True)
            
            # Write metadata.json
            metadata = {
                "id": slug,
                "title": title.replace("(Leetcode Premium)", "").strip(),
                "category": current_category,
                "difficulty": difficulty.capitalize(),
                "url": url,
                "premium": "(Leetcode Premium)" in title
            }
            with open(os.path.join(q_dir, "metadata.json"), "w", encoding="utf-8") as meta_f:
                json.dump(metadata, meta_f, indent=4)
                
            # Write description.md
            with open(os.path.join(q_dir, "description.md"), "w", encoding="utf-8") as desc_f:
                desc_f.write(f"# {metadata['title']}\n\n")
                desc_f.write(f"**Difficulty**: {metadata['difficulty']} | **Category**: {metadata['category']}\n\n")
                desc_f.write(f"[View on LeetCode]({url})\n\n")
                desc_f.write("Problem description goes here...\n")
                
            # Write test_cases.json
            test_cases = [
                {
                    "input": "test input",
                    "expected_output": "test output"
                }
            ]
            with open(os.path.join(q_dir, "test_cases.json"), "w", encoding="utf-8") as tc_f:
                json.dump(test_cases, tc_f, indent=4)
                
    print("Successfully generated all questions from Gist!")

if __name__ == "__main__":
    main()
