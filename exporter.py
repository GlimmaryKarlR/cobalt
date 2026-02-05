import json
from playwright.sync_api import sync_playwright

def export_netscape_cookies():
    with sync_playwright() as p:
        # 1. Launch a browser (headed or headless)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 2. Navigate to trigger the cookies (Login here if needed)
        page.goto("https://www.youtube.com")

        # 3. Get all cookies from the context
        raw_cookies = context.cookies()

        # 4. IMPLEMENT THE EXTENSION LOGIC (from cookie_format.mjs)
        netscape_lines = [
            "# Netscape HTTP Cookie File",
            "# https://curl.haxx.se/rfc/cookie_spec.html",
            "# This is a generated file! Do not edit.",
            ""
        ]

        for c in raw_cookies:
            # Replicating jsonToNetscapeMapper
            domain = c['domain']
            include_sub = "TRUE" if domain.startswith('.') else "FALSE"
            path = c['path']
            secure = "TRUE" if c['secure'] else "FALSE"
            expiry = str(int(c.get('expires', 0)))
            name = c['name']
            value = c['value']

            line = f"{domain}\t{include_sub}\t{path}\t{secure}\t{expiry}\t{name}\t{value}"
            netscape_lines.append(line)

        # 5. Save exactly like save_to_file.mjs
        with open("cookies.txt", "w") as f:
            f.write("\n".join(netscape_lines) + "\n")
        
        print("Success: cookies.txt generated using Downr logic.")
        browser.close()

if __name__ == "__main__":
    export_netscape_cookies()
