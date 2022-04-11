# Standard library imports
import sys
import time
from tkinter import Y
import urllib.parse as urlparse
import os
import re
import json
import pandas as pd
from pandas import DataFrame, json_normalize
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Third party imports
from bs4 import BeautifulSoup
import requests

# Local library imports 
import depopScraper.payload as pl

URL_ENDPOINT = 'https://webapi.depop.com/api/v2/search/products/'
LISTING_BASE_URL = 'https://www.depop.com/products/'
GMAIL_SERVER = 'smtp.gmail.com'
GMAIL_PORT = 465
GMAIL_USER = 'kennyafitzgerald@gmail.com'
GMAIL_PASSWORD = 'yhhwjqbeklwmxprk'
GMAIL_RECEIVER = 'kennyafitzgerald@gmail.com'

class Search():

    def __init__(self, search_name) -> None:
        super().__init__()
        self.search_name = search_name
        self.seen_listings_file = f'depopScraper/data/seen_listings.txt'
        self.seen_listings = self._load_seen_listings()
        self.params = self._get_params_from_config()
        self.df_filters = self._get_df_filters_from_config()
    
    def _get_params_from_config(self) -> dict:

        payload = pl.Payload(self.search_name)

        return payload.params
    
    def _get_df_filters(self) -> dict:

        payload = pl.Payload(self.search_name)

        return payload.df_filters

    def _pull_results(self) -> DataFrame:

        page = requests.get(URL_ENDPOINT, params=self.params)

        self.page = page

        results_json = json.loads(page.text)['products']

        results = pd.DataFrame(results_json)

        results = pd.concat([pd.DataFrame(results), 
                        json_normalize(results['price'])], 
                        axis=1).drop('price', 1)
        
        results = results[~results['id'].isin(self.seen_listings)]

        results = results.loc[(results[list(self.df_filters)] == pd.Series(self.df_filters)).all(axis=1)]

        results['html_link'] = '<p><a href="' + LISTING_BASE_URL + results['slug'] + '">' + results['slug'] + ': ' + results['priceAmount'].astype(str) + results['currencyName'] + '</a></p>'

        return results

    def _load_seen_listings(self) -> list:

        seen_listings = []

        if os.path.exists(self.seen_listings_file):
            with open(self.seen_listings_file, 'r') as f:
                seen_listings = [line.strip() for line in f]

        return seen_listings

    def _write_seen_listings(self, seen_listings):
        """ Writes the completed listings list to a .txt file
        """
        if os.path.exists(self.seen_listings_file):
            textfile = open(self.seen_listings_file, "w")
            for element in seen_listings:
                textfile.write(element + "\n")
            textfile.close()

    def _send_gmail(self, content):
        """ Send an email notification through gmail.

            Reads the configuration from emailer_config.ini

            Raises:
                SMTPException, if one occured.
        """

        msg = MIMEMultipart('alternative')
        msg['From'] = GMAIL_USER
        msg['To'] = GMAIL_RECEIVER
        msg['Subject'] = f'Depop search results for {self.search_name}'

        html_part = MIMEText(content, 'html')
        msg.attach(html_part)

        try:
            server = smtplib.SMTP_SSL(GMAIL_SERVER, GMAIL_PORT)
            server.ehlo()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, GMAIL_RECEIVER, msg.as_string())
            server.close()
        except:  
            raise

    def search(self):

        results = self._pull_results()

        self.seen_listings.append(list(results['id']))

        # Write seen listings 
        self._write_seen_listings(self.seen_listings)

        # Send an email with the results
        if len(results) > 0:
            self._send_gmail('\n'.join(list(results['html_link'])))


    


search = Search('carhartt_chase')

search.search()

search.page.url