import os, re
pattern = re.compile(r"templates\.TemplateResponse\((['\"][^'\"]+['\"]),\s*\{")
for root, dirs, files in os.walk("src/community_hub/routes"):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            with open(path, "r") as f:
                content = f.read()
            new_content = pattern.sub(r"templates.TemplateResponse(request=request, name=\1, context={", content)
            if new_content != content:
                with open(path, "w") as f:
                    f.write(new_content)
                print(f"Updated {path}")
