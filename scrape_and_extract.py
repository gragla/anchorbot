import asyncio
from playwright.async_api import async_playwright
import trafilatura
from pathlib import Path
import logging
from urllib.parse import urlparse, urljoin
import time
import aiofiles
import sys
from typing import Set, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HeadlessScraper:
    def __init__(self, output_dir: str = "scraped_content", max_pages: int = 100):
        self.html_dir = Path(output_dir) / "html"
        self.markdown_dir = Path(output_dir) / "markdown"
        self.html_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.max_pages = max_pages
        self.visited_urls: Set[str] = set()

    def get_safe_filename(self, url: str) -> str:
        """Create safe filename from URL"""
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        if not path:
            path = 'index'
        return path.replace('/', '_').replace('.html', '') + '.html'

    async def save_html(self, url: str, content: str) -> str:
        """Save HTML content to file"""
        filename = self.get_safe_filename(url)
        filepath = self.html_dir / filename
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(content)
        return str(filepath)

    async def crawl_page(self, page, url: str, base_domain: str) -> List[str]:
        """Crawl a single page and extract links"""
        if url in self.visited_urls or len(self.visited_urls) >= self.max_pages:
            return []

        try:
            self.visited_urls.add(url)
            logger.info(f"Crawling: {url}")

            # Navigate to page and wait for content to load
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(2000)  # Additional wait for dynamic content

            # Get page content after JavaScript execution
            content = await page.content()
            
            # Save HTML and record URL mapping
            filename = self.get_safe_filename(url)
            await self.save_html(url, content)
            
            # Save URL mapping
            mapping_file = self.html_dir / 'url_mapping.txt'
            with open(mapping_file, 'a', encoding='utf-8') as f:
                f.write(f"{filename}\t{url}\n")

            # Extract all links
            links = await page.evaluate('''
                () => {
                    const links = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        links.push(a.href);
                    });
                    return links;
                }
            ''')

            # Filter links
            filtered_links = [
                link for link in links
                if urlparse(link).netloc == base_domain
                and not link.endswith(('.pdf', '.zip', '.png', '.jpg', '.jpeg'))
                and '#' not in link
                and link not in self.visited_urls
            ]

            return filtered_links

        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            return []

    async def crawl_site(self, start_url: str):
        """Crawl entire site using Playwright"""
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800}
            )
            page = await context.new_page()

            base_domain = urlparse(start_url).netloc
            urls_to_crawl = [start_url]
            
            try:
                while urls_to_crawl and len(self.visited_urls) < self.max_pages:
                    url = urls_to_crawl.pop(0)
                    new_urls = await self.crawl_page(page, url, base_domain)
                    urls_to_crawl.extend(new_urls)
                    await asyncio.sleep(1)  # Rate limiting
            
            finally:
                await browser.close()

    def convert_to_markdown(self):
        """Convert all HTML files to Markdown using trafilatura"""
        logger.info("Converting HTML files to Markdown...")
        
        # First, create a mapping of HTML filenames to their original URLs
        url_mapping = {}
        metadata_file = self.html_dir / 'url_mapping.txt'
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if '\t' in line:
                        filename, url = line.strip().split('\t')
                        url_mapping[filename] = url
        
        for html_file in self.html_dir.glob('*.html'):
            try:
                # Read HTML content
                with open(html_file, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                # Extract content using trafilatura
                downloaded = trafilatura.load_html(html_content)
                
                if downloaded:
                    # Extract main content
                    markdown_content = trafilatura.extract(
                        downloaded,
                        output_format='markdown',
                        include_tables=True,
                        include_images=True,
                        include_links=True,
                        include_formatting=True
                    )
                    
                    # Extract metadata
                    metadata = trafilatura.extract_metadata(downloaded)
                    
                    if markdown_content:
                        # Create markdown file
                        markdown_file = self.markdown_dir / html_file.name.replace('.html', '.md')
                        
                        # Build content with frontmatter
                        content_parts = ["---"]
                        if metadata:
                            if metadata.title:
                                content_parts.append(f'title: "{metadata.title}"')
                            if metadata.author:
                                content_parts.append(f'author: "{metadata.author}"')
                            if metadata.date:
                                content_parts.append(f'date: "{metadata.date}"')
                            if metadata.description:
                                content_parts.append(f'description: "{metadata.description}"')
                        
                        # Add source URL if available
                        if html_file.name in url_mapping:
                            content_parts.append(f'url: "{url_mapping[html_file.name]}"')
                        
                        content_parts.append(f'source_file: "{html_file.name}"')
                        content_parts.append("---\n")
                        
                        if metadata and metadata.title:
                            content_parts.append(f"# {metadata.title}\n")
                            
                        content_parts.append(markdown_content)
                        
                        # Write markdown file
                        with open(markdown_file, 'w', encoding='utf-8') as f:
                            f.write('\n'.join(content_parts))
                            
                        logger.info(f"Converted {html_file.name} to markdown")
                    else:
                        logger.warning(f"No content extracted from {html_file.name}")
                else:
                    logger.warning(f"Could not load HTML from {html_file.name}")
                    
            except Exception as e:
                logger.error(f"Error converting {html_file.name}: {e}")

async def main():
    if len(sys.argv) != 3:
        print("Usage: python script.py <start_url> <output_dir>")
        return
        
    start_url = sys.argv[1]
    output_dir = sys.argv[2]
    
    scraper = HeadlessScraper(output_dir=output_dir, max_pages=250)
    
    # Phase 1: Crawl and save HTML
    logger.info("Starting crawl phase...")
    start_time = time.time()
    await scraper.crawl_site(start_url)
    
    # Phase 2: Convert to Markdown
    logger.info("Starting conversion phase...")
    scraper.convert_to_markdown()
    
    duration = time.time() - start_time
    logger.info(f"""
Scraping complete:
- Pages processed: {len(scraper.visited_urls)}
- Time taken: {duration:.2f} seconds
- Output directory: {output_dir}
""")

if __name__ == "__main__":
    asyncio.run(main())