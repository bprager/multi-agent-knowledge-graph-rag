#!/usr/bin/env python3

import logging
import os
import time
import yaml
import sys
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sec_api import QueryApi, PdfGeneratorApi

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for more details
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s - %(funcName)s:%(lineno)d: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("urllib3").setLevel(logging.INFO)  # Suppress urllib logs


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )
    sec_api_key: SecretStr
    logging_level: str


def handle_api_error(error_message: str) -> None:
    """Handle API errors gracefully and exit if rate limits are exceeded."""
    if "429" in error_message:
        logging.error("🚨 API rate limit exceeded. Exiting gracefully.")
        sys.exit(1)  # Exit the script to prevent unnecessary requests
    else:
        logging.error("❌ API Error: %s", error_message)


def download_pdf(pdf_generator_api: PdfGeneratorApi, filing_url: str, filename: str, output_dir: str) -> None:
    """Generate a PDF from an SEC filing URL and save it locally."""
    filepath = os.path.join(output_dir, filename)

    try:
        pdf_data = pdf_generator_api.get_pdf(filing_url)

        # Write data safely
        with open(filepath, "wb") as file:
            file.write(pdf_data)

        logging.info("✅ Saved: %s", filename)

    except Exception as e:
        logging.error("❌ Failed to generate PDF for %s: %s", filename, e)


def fetch_sec_filings(query_api: QueryApi, pdf_generator_api: PdfGeneratorApi, ticker: str, filing_types: list, output_dir: str) -> None:
    """Fetch SEC filings for a given ticker and download relevant PDFs."""
    logging.debug("🔍 Fetching reports for %s...", ticker)

    query = {
        "query": {
            "query_string": {
                "query": f"ticker:{ticker} AND formType:({' OR '.join(filing_types)})"
            }
        },
        "from": "0",
        "size": "5",  # Fetch the latest available filings of the given types
        "sort": [{"filedAt": {"order": "desc"}}],
    }

    try:
        response = query_api.get_filings(query)
        filings = response.get("filings", [])

        if not filings:
            logging.warning("⚠️ No filings found for %s", ticker)
            return

        for filing in filings:
            filing_url = filing.get("linkToFilingDetails")
            filing_type = filing.get("formType")
            filed_date = filing.get("filedAt", "").split("T")[0]

            if filing_url:
                filename = f"{ticker}_{filing_type}_{filed_date}.pdf"
                download_pdf(pdf_generator_api, filing_url, filename, output_dir)

    except Exception as e:
        error_message = str(e)
        handle_api_error(error_message)


def main():
    """Main entry point for fetching and downloading SEC filings."""
    settings = ModelSettings()  # Load settings from .env
    logging.getLogger().setLevel(settings.logging_level.upper())  # Adjust log level dynamically
    logging.info("🚀 Starting SEC Filing Fetcher...")

    # Initialize SEC API clients
    query_api = QueryApi(api_key=settings.sec_api_key.get_secret_value())
    pdf_generator_api = PdfGeneratorApi(api_key=settings.sec_api_key.get_secret_value())

    # Read tickers from the YAML file
    yaml_file = "ai_companies.yaml"

    try:
        with open(yaml_file, "r", encoding="utf-8") as file:
            ai_companies = yaml.safe_load(file)["ai_companies"]
        tickers = [company["ticker"] for company in ai_companies]
        logging.debug("📈 Tickers loaded: %s", tickers)
    except (FileNotFoundError, KeyError) as e:
        logging.error("❌ Failed to read tickers from YAML: %s", e)
        return

    # Ensure output directory exists
    output_dir = "SEC_Filings"
    os.makedirs(output_dir, exist_ok=True)

    # SEC Filing Types to Query
    filing_types = ["10-K", "10-Q", "8-K", "1-SA", "1-U"]

    # Process filings for each ticker
    for ticker in tickers:
        fetch_sec_filings(query_api, pdf_generator_api, ticker, filing_types, output_dir)
        time.sleep(1)  # Avoid rate limits

    logging.info("🎉 Download complete!")


if __name__ == "__main__":
    start_time = time.time()

    try:
        main()
    except KeyboardInterrupt:
        logging.warning("🛑 Script interrupted by user.")
        sys.exit(0)
    except Exception as e:
        logging.error("❌ Unhandled exception: %s", e)
        sys.exit(1)

    # Log execution time
    elapsed_time = time.time() - start_time
    hours, rem = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(rem, 60)
    logging.info("⏱️ Execution time: %02d:%02d:%05.2f", int(hours), int(minutes), seconds)

