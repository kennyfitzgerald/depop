# Standard library imports
from distutils.command.config import config
import yaml
import json
from urllib.parse import urlencode
import time
import random
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Third party imports
import requests
import pandas as pd
import numpy as np
from pyaml_env import parse_config

# Local library imports
# --


# Constants
URL_API_ENDPOINT = 'https://webapi.depop.com/api/v2/search/products/'
URL_LISTING_ENDPOINT = 'https://depop.com/products/'

# Functions

def dict_lists_to_strings(dict):
    """ Takes a dictionary of parameters as input and converts all lists within that dictionary
        to a concatenated string that is recognised by the Depop API. """

    new_dict = {k: ('%2C'.join(v) if isinstance(v, list) else v) for k, v in dict.items()}

    return new_dict


def filters_to_pandas_query(dict):
    """ Takes a dictionary with keys corresponding to the JSON keys found in the API response object 
        prefixed with either 'min_', 'max_', 'list_' or no prefix for booleans, and values corresponding
        to the desired value to filter each result by, returns a string which can be fed into the pandas 
        query function. """

    filters = {k:v for k, v in dict.items() if v is not None}
    columns = [k.replace('max_', '', 1).replace('min_', '', 1).replace('list_', '', 1) for k in filters.keys()]
    operators = ['<=' if k.startswith('max_') else '>=' if k.startswith('min_') else ' in ' if k.startswith('list_') else '==' for k, v in filters.items()]
    values = [v for k, v in filters.items()]

    query_string = ' & '.join([f'({c} {o} {v})' for c, o, v in zip(columns, operators, values)])

    return query_string


def separate_pd_query_strings(dict):
    """ Takes a dictionary of parameters as input and extracts the 'filters' string generated 
        by the get_search_params function, returning a separate dictonary containing query
        string values for each search. """
    
    pd_query_strings = {k: [v for k, v in v.items() if k=='filters'][0] for k, v in dict.items()}

    return pd_query_strings
    

def get_params(config_filepath, search_ids):
    """ Takes a config file and a set of search IDs and returns two dictionaries containing the url query
        and post API call pandas query strings respectively. """

    # Load config file
    with open(config_filepath, "r") as f:
        config = yaml.safe_load(f)

    # Select specified search IDs only
    params = {k: v for k, v in config.items() if k in search_ids}

    for p in params.keys():

        # Convert lists to API readable string
        params[p] = dict_lists_to_strings(params[p])

        # Convert filters to a pandas query string
        params[p]['filters'] = filters_to_pandas_query(params[p]['filters'])

    # Extract query strings for filtering after API call
    pd_query_strings = separate_pd_query_strings(params)

    # Separate filters from search payloads
    payload = {k: {k:v for k, v in v.items() if k!='filters'} for k, v in params.items()}

    # Remove whitespace and create URL string
    urls_dict = {}
    for s in search_ids:
        payload[s] = {k: v.replace(' ', '+') for k, v in payload[s].items()}

        url = f'{URL_API_ENDPOINT}?' + '&'.join([f'{k}={v}' for k, v in payload[s].items() if v != ''])

        urls_dict[s] = url

    return urls_dict, pd_query_strings

def get_query_results(url, filter_query_string):
    """ Takes a search URL and a query string and returns 
        a dataframe with the relevant filters applied  
    """

    # Make API request
    page = requests.get(url)

    # Convert JSON reponse into JSON object
    results_json = json.loads(page.text)['products']

    # Convert into Pandas DataFrame
    results = pd.DataFrame(results_json)
    results = pd.concat([pd.DataFrame(results), pd.json_normalize(results['price'])], axis=1).drop(columns='price')

    # Apply filters to results, convert datatypes to numeric where applicable
    results = pd.DataFrame(results)
    results = results.apply(pd.to_numeric, errors='ignore')
    results = results.query(filter_query_string, engine='python')

    # If no results, pass
    if len(results)==0:
        return results

    # Add additional columns for total price and listing URL
    results['url'] = URL_LISTING_ENDPOINT + results['slug']

    # Sometimes the discounted price column doesn't exist - if this happens we set to the priceAmount
    try:
        results['discountedPriceAmount'] = np.where(results['discountedPriceAmount'].isna(), results['priceAmount'], results['discountedPriceAmount'])
        results['total_cost'] = results['discountedPriceAmount'] + results['nationalShippingCost']
    except:
        results['total_cost'] = round(0 + results['priceAmount'], 2)
    
    # Add columns for image URL and formatted user and title from slug
    results['user'] = results.slug.str.split('-').str[0].str.title()
    results['title'] = (results.slug.str.split('-').str[1:]).str.join(' ').str.title()
    results['image_url'] = results.preview.str['480']

    # Add HTML for email
    results['html'] = results.agg(lambda x: f"<li><a href=\"{x['url']}\"><img src=\"{x['image_url']}\" width=\"80\" /> {x['title']} - £{x['total_cost']} </a></li>", axis=1)

    # Wait
    time.sleep(random.randint(1, 2))
    
    return results


def get_all_query_results(config_filepath, search_ids):
    """ Takes a config file and a set of search IDs and returns a 
        binded dataframe of all filtered results.
    """

    # Create URLs and additional filters for each specified search
    urls_dict, pd_query_strings = get_params(config_filepath, search_ids)

    # Loop through searches and create a dictionary of pandas dataframes
    results_dict = {}

    for search_id in search_ids:

        results_dict[search_id] =  get_query_results(urls_dict[search_id], pd_query_strings[search_id])

        # Append column with search string 
        results_dict[search_id]['search_id'] = search_id    

    # Concatenate pandas dataframes and convert datatypes
    results = pd.concat(results_dict.values())
    results = results.convert_dtypes()
    results = pd.DataFrame(results)

    # Filter out seen listings 
    seen_listings = read_seen_listings()
    results = results[~results['id'].isin(seen_listings)]

    return results

def log_seen_listings(df):
    """ Takes a dataframe with an 'id' column name and saves the IDs of listings that have been sent out in a text file.
    """
    filepath = 'data/seen_listings/seen_listings.txt'

    seen_listings = list(df['id'])
    
    textfile = open(filepath, "a")

    for element in seen_listings:
        textfile.write(str(element) + "\n")

    textfile.close()


def read_seen_listings():
    """ Checks if the 'seen_listings.txt' file exists and if it does returns a list of IDs that have previously been seen
        in search results.
    """

    seen_listings = []

    if os.path.exists('data/seen_listings/seen_listings.txt'):
        with open('data/seen_listings/seen_listings.txt', 'r') as f:
            seen_listings = [int(line.strip()) for line in f]

    return seen_listings


def load_emailer_config(email_config_filepath):
    """ Takes an email config filepath as input and returns a dictionary of email credentials
    """

    # Load config file
    email_config = parse_config(email_config_filepath)['email_config']

    return email_config


def send_email(email_config_filepath, df):
    """ Takes an email config filepath and a dataframe of search results as input and sends a formatted 
        email as results
    """

    # Load config from email config file
    email_config = load_emailer_config(email_config_filepath)

    # Extract individual config values
    server = email_config['server']
    port = email_config['port']
    user = email_config['user']
    password = email_config['password']
    receiver = email_config['receiver']

    # Extract search IDs from dataframe
    returned_search_ids = list(set(df['search_id']))

    # Convert DF to HTML 
    content = df_to_html(df, returned_search_ids)

    # Send Email
    msg = MIMEMultipart('alternative')
    msg['From'] = user
    msg['To'] = receiver
    msg['Subject'] = f"Depop search results for {', '.join(returned_search_ids)}"

    html_part = MIMEText(content, 'html')
    msg.attach(html_part)

    try:
        server = smtplib.SMTP_SSL(server, port)
        server.ehlo()
        server.login(user, password)
        server.sendmail(user, receiver, msg.as_string())
        server.close()
        print("Email Sent.")
    except:  
        raise

def df_to_html(df, returned_search_ids):
    """ Takes a dataframe of search results and search IDs of that dataframe as input and returns a HTML string of formatted results, ready
        to send as an email.
    """

    # Initialise empty list for HTML to be stored
    results_lists = []

    # Loops through each result set to create a HTML list to add to email
    for r in returned_search_ids:

        df_temp = df.query(f"search_id == '{r}'")
        html = f"<h3>Search Query: {r}</h3> <ol> {' '.join(list(df_temp['html']))} </ol>"
        results_lists.append(html)

    # Combines HTML for all results to be put into final email.
    html_final = f"<h1>Depop Search Results</h1> {' '.join(results_lists)}"
    
    return html_final


def run_search(search_ids=None):
    """ Takes a search config filepath, an emailer config filepath, and search IDs as they appear in the 
        search config file path. Sends an email of filtered results to the email address specified and logs 
        the listing IDs that were sent out  
    """

    # If search IDs are unspecified then it uses all in the config file. 
    if search_ids is None:
        with open('depopScraper/config/config.yml', "r") as f:
            search_ids = list(yaml.safe_load(f).keys())

    # Get results
    df = get_all_query_results('depopScraper/config/config.yml', search_ids)

    # Log number of results found 
    results_found = len(df)

    # If no results, send no email.
    if results_found==0:
        print("No Results Found.")
        pass
    else:
        # Send Email
        print(f"{results_found} results found. Sending email..")
        send_email('depopScraper/config/emailer_config.yml', df)

        # Log listings sent
        log_seen_listings(df)
