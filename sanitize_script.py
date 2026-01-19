import re
import os

path = r'd:\SMC\strategy\risk_management.py'
if os.path.exists(path):
    with open(path, 'r', encoding='ascii', errors='ignore') as f:
        content = f.read()
    
    # Replace triple double quotes with comments
    # This is a bit naive but should work for this file
    def replacer(match):
        inner = match.group(1)
        lines = inner.split('\n')
        return '\n'.join('        # ' + l.strip() for l in lines)

    # Simplified regex for this specific file structure
    content = re.sub(r'\"\"\"(.*?)\"\"\"', replacer, content, flags=re.DOTALL)
    
    # Also clean up any remaining non-ascii just in case
    content = ''.join(i if ord(i) < 128 else ' ' for i in content)
    
    # Normalize newlines
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        f.write(content)
    print("Successfully sanitized risk_management.py")
else:
    print("File not found")
