"""
Code to work with the Metabolomics Tools Wiki

The "wiki" uses a Google Sheets spreadsheet for its data store:
https://docs.google.com/spreadsheets/d/1bEO9_SYznC9rrtzJdHtpjdKL-AEPYkLANBgQDpx52tI

The headers should be:
 - Software
 - Description
 - Functionality
 - Instrument Data Type
 - Approaches
 - Computer Skills
 - Software Type
 - Interface
 - Operating System (OS)
 - Language
 - Version
 - Dependencies
 - Input Formats - Open
 - Input Formats - Proprietary
 - Published
 - Last Updated
 - License
 - Website
 - Paper
 - PMID
 - SoftwareLink
 - WebsiteLink
 - PaperLink
"""

from typing import Iterable, Mapping, Optional

import csv
import io
import json

import requests


class MetabolomicsToolsWiki:
    """
    Client for the Metabolomics Tools Wiki website.

    Examples
    --------
    ```
        # Print all PubMed IDs found.
        print('\\n'.join(MetabolomicsToolsWiki.pmids()))
        # Download the CSV.
        csvdata = MetabolomicsToolsWiki.download()
    ```
    """

    URL = "https://docs.google.com/spreadsheets/d/1bEO9_SYznC9rrtzJdHtpjdKL-AEPYkLANBgQDpx52tI"

    @staticmethod
    def download() -> str:
        url = f"{MetabolomicsToolsWiki.URL}/export?exportFormat=csv"
        req = requests.get(url)
        if not req.ok:
            return ""
        return req.text

    @staticmethod
    def json(tools: Optional[Iterable[Mapping[str, str]]] = None) -> str:
        if not tools:
            tools = MetabolomicsToolsWiki.tools()
        return json.dumps(list(tools))

    @staticmethod
    def pmids(tools: Optional[Iterable[Mapping[str, str]]] = None) \
            -> Iterable[str]:
        if not tools:
            tools = MetabolomicsToolsWiki.tools()
        for tool in tools:
            pmid = tool.get("PMID", "").strip()
            if pmid.isnumeric():
                yield pmid

    @staticmethod
    def tools() -> Iterable[Mapping[str, str]]:
        csvdata = MetabolomicsToolsWiki.download()
        file = io.StringIO(csvdata)
        reader = csv.DictReader(file)
        for row in reader:
            yield row
