import yaml

class Payload():

    def __init__(self, query_name) -> None:
        super().__init__()
        self.query_name = query_name
        self.params = self._get_params()
        self.df_filters = self._get_df_filters()
    
    def _get_params(self):

        with open("config.yml", "r") as f:
            config = yaml.safe_load(f)
        
        params = config['searches'][self.query_name]['q_params']

        params.update({k: '%2C'.join(v) for k, v in params.items() if isinstance(v, list)})

        return params
    
    def _get_df_filters(self):

        with open("config.yml", "r") as f:
            config = yaml.safe_load(f)
        
        df_filters = config['searches'][self.query_name]['df_filters']

        return df_filters

