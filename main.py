# Local Library Imports
from depopScraper.search import *

# Setting with copy warning
pd.options.mode.chained_assignment = None  # default='warn'

if __name__ == "__main__":

    # Optionally enter a list of search IDs as they appear in the config file.
    run_search()