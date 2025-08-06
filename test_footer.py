#!/usr/bin/env python3
"""Test script to verify the footer implementation."""

import sys
from pathlib import Path


def test_footer_files_exist():
    """Test that all required footer files exist."""
    required_files = ["docs/_footer.md", "docs/css/navigation_cards.css", "mkdocs.yml"]

    for file_path in required_files:
        if not Path(file_path).exists():
            print(f"❌ Missing required file: {file_path}")
            return False
        else:
            print(f"✅ Found required file: {file_path}")

    return True


def test_mkdocs_config():
    """Test that mkdocs.yml contains the required configuration."""
    with open("mkdocs.yml") as f:
        content = f.read()

    required_items = [
        "https://fonts.googleapis.com/icon?family=Material+Icons",
        "css/navigation_cards.css",
        "include-markdown",
    ]

    for item in required_items:
        if item in content:
            print(f"✅ Found in mkdocs.yml: {item}")
        else:
            print(f"❌ Missing in mkdocs.yml: {item}")
            return False

    return True


def test_footer_content():
    """Test that footer contains expected content."""
    with open("docs/_footer.md") as f:
        content = f.read()

    expected_elements = ["nav-card", "material-icons", "bug_report", "help", "GitHub", "Slack"]

    for element in expected_elements:
        if element in content:
            print(f"✅ Found in footer: {element}")
        else:
            print(f"❌ Missing in footer: {element}")
            return False

    return True


def test_pages_include_footer():
    """Test that main pages include the footer."""
    pages_to_check = ["docs/index.md", "docs/usage.md", "docs/installation.md"]

    for page in pages_to_check:
        if Path(page).exists():
            with open(page) as f:
                content = f.read()

            if '{% include-markdown "_footer.md" %}' in content:
                print(f"✅ Footer included in: {page}")
            else:
                print(f"❌ Footer missing in: {page}")
                return False
        else:
            print(f"⚠️  Page not found: {page}")

    return True


def main():
    """Run all tests."""
    print("🧪 Testing footer implementation...")
    print("=" * 50)

    tests = [test_footer_files_exist, test_mkdocs_config, test_footer_content, test_pages_include_footer]

    all_passed = True
    for test in tests:
        print(f"\n📋 Running {test.__name__}...")
        if not test():
            all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 All tests passed! Footer implementation looks good.")
        return 0
    else:
        print("❌ Some tests failed. Please check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
