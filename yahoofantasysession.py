from pprint import pprint
import logging
import json
from pathlib import Path
from requests_oauthlib import OAuth2Session
from cachecontrol import CacheControlAdapter
from cachecontrol.heuristics import ExpiresAfter
from cachecontrol.caches import FileCache
from time import sleep


class YahooSession:
    def __init__(self, **kwargs):
        """
        Base class for Yahoo Fantasy API OAUTH2 requests

        :Keyword Arguments:
            request_delay (double): seconds to sleep between requests for rate limiting
            cache_expire_hours (int): hours cached requests will remain valid
            web_cache_dir (string): specify a directory name / location for cache storage

        """

        logging.getLogger(__name__).addHandler(logging.NullHandler())

        self.request_delay = 0.1
        self.cache_expire_hours = 168
        self.web_cache_dir = ".yahoo_web_cache"

        # delay between requests
        if kwargs.get("request_delay"):
            self.request_delay = kwargs["request_delay"]

        # cached website expiration hours
        if kwargs.get("cache_expire_hours"):
            self.cache_expire_hours = kwargs["cache_expire_hours"]

        # web cache directory name
        if kwargs.get("web_cache_dir"):
            self.web_cache_dir = kwargs["web_cache_dir"]

        self.urls = []
        self.cached_urls = {}

        # Yahoo api credentials / authorization local storage
        self.credentials_file = ".yahoo_fantasy_credentials.json"
        self.auth_file = ".yahoo_fantasy_auth_token.json"

        # Yahoo OAuth URLs
        self.auth_base_url = "https://api.login.yahoo.com/oauth2/request_auth"
        self.access_token_url = "https://api.login.yahoo.com/oauth2/get_token"

        # Yahoo Credentials... populate from credentials file
        self.client_id = ""
        self.client_secret = ""
        self.callback_url = "oob"

        # Yahoo Auth Token... populate from authorization file
        self.auth_token_dict = {}

        self._load_credentials()
        self._load_authorization()

        self.s = None
        self._load_session()

    def _load_credentials(self):
        """
        Loads credentials from file
        Args:
            None
        Returns:
            None
        """
        creds_path = Path(self.credentials_file)

        if not creds_path.exists():
            creds_dict = {
                "client_id": "",
                "client_secret": "",
                "callback_url": "oob",
            }
            creds_path.write_text(json.dumps(creds_dict, indent=1))

            raise Exception(
                f"Credentials file is required, {str(creds_path)} has been created, please modify it with your application credentials from https://developer.yahoo.com/apps/"
            )

        logging.debug(f"loading credentials file...")
        creds_dict = json.loads(creds_path.read_text())

        self.client_id = creds_dict["client_id"]
        assert self.client_id != "", "Credentials file needs to be updated"

        self.client_secret = creds_dict["client_secret"]
        assert self.client_secret != "", "Credentials file needs to be updated"

        self.callback_url = creds_dict["callback_url"]

    def _load_authorization(self):
        """
        Loads authorization from file
        Args:
            None
        Returns:
            None
        """
        auth_path = Path(self.auth_file)

        if not auth_path.exists():
            logging.debug(f"Authorization file does not exist, creating...")
            token_dict = self._get_new_auth_token()
            auth_path.write_text(json.dumps(token_dict, indent=1))

        self.auth_token_dict = json.loads(auth_path.read_text())

    def _get_new_auth_token(self):
        """
        Generates a yahoo api authorization token
        Args:
            None
        Returns:
            authorization token dict
        """
        # Create a session to the auth url with your client ID, it will return and authorization link
        yahoo_auth = OAuth2Session(self.client_id, redirect_uri=self.callback_url)
        authorization_url, state = yahoo_auth.authorization_url(self.auth_base_url)

        # Prompt use to follow the link, authorize, and enter the given code to the prompt
        print("Please go to\n%s\nand authorize" % authorization_url)
        authorization_code = input("\nEnter the authorization code here: ")
        token_dict = yahoo_auth.fetch_token(
            self.access_token_url,
            client_secret=self.client_secret,
            code=authorization_code,
        )

        return token_dict

    def _auth_file_saver(self, token_dict):
        """
        Saves a session's authorization token to authorization file
        Args:
            Authorization Token
        Returns:
            None
        """
        # will be called when: token_dict['expires_at'] < datetime.datetime.now().timestamp()
        auth_path = Path(self.auth_file)
        logging.info(
            f"The session called auth refresh because of 'expired_at'. Saving new refreshed-auth to {str(auth_path)}"
        )
        auth_path.write_text(json.dumps(token_dict, indent=1))

    def _load_session(self):
        """
        Creates a session using defined settings
        Args:
            None
        Returns:
            None
        """
        # Provide the required arguments for our session to pass when it attempts to auto update the token
        token_updater_args = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        # set up the session client
        self.s = OAuth2Session(
            self.client_id,
            token=self.auth_token_dict,
            auto_refresh_url=self.access_token_url,
            auto_refresh_kwargs=token_updater_args,
            token_updater=self._auth_file_saver,
        )

        self.s.mount(
            "https://",
            CacheControlAdapter(
                cache=FileCache(self.web_cache_dir),
                cache_etags=False,
                heuristic=ExpiresAfter(hours=self.cache_expire_hours),
            ),
        )

    def get(self, url, return_object=False):
        # Perform a get request on given url
        r = self.s.get(url)
        assert r.headers.get("etag") == None

        # The cached request's filename will be...
        cached_url = FileCache.encode(url)
        # Delay to minimize load on yahoo servers
        # Delay only if delay != 0 and response was not cached
        if self.request_delay and not r.from_cache:
            sleep(self.request_delay)

        if not r.from_cache:
            self.cached_urls[cached_url] = r.url

        self.urls.append(r.url)
        r.raise_for_status()

        if return_object:
            return r
        else:
            return r.text


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(funcName)s - %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
        handlers=[
            logging.FileHandler("debug.log", mode="w"),
            logging.StreamHandler(),
        ],
    )

    sess = YahooSession()
    response = sess.get(
        "https://fantasysports.yahooapis.com/fantasy/v2/game/nfl",
        return_object=True,
    )

    print(f"{response.from_cache=}")
    game_id_location = response.text.find("game_id")
    game_id = response.text[game_id_location - 1 : game_id_location + 21]
    print(f"{game_id=}")
