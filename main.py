#!/usr/bin/env python3
"""
Coursera Material Downloader
Downloads all course materials from enrolled Coursera courses/professional certificates.
"""
import argparse
from coursera.scraper import CourseraScraper

def main():
    parser = argparse.ArgumentParser(
        description="Download all materials from Coursera Professional Certificate"
    )
    parser.add_argument(
        "--email",
        default="yoni.kremer@gmail.com",
        help="Google account email (default: yoni.kremer@gmail.com)"
    )
    parser.add_argument(
        "--cert-url",
        default="https://www.coursera.org/professional-certificates/google-advanced-data-analytics",
        help="Professional certificate URL"
    )
    parser.add_argument(
        "--output-dir",
        default="coursera_downloads",
        help="Output directory for downloads (default: coursera_downloads)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended for login)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Coursera Material Downloader")
    print("=" * 60)
    print(f"Email: {args.email}")
    print(f"Certificate: {args.cert_url}")
    print(f"Output directory: {args.output_dir}")
    print("=" * 60)

    scraper = CourseraScraper(
        email=args.email,
        download_dir=args.output_dir,
        headless=args.headless
    )

    # Note: Currently the course list is hardcoded in download_certificate inside the scraper
    # You might want to pass it or extract it from cert_url in the future.
    scraper.download_certificate(cert_url=args.cert_url)

if __name__ == "__main__":
    main()
