import json
import matplotlib.pyplot as plt

def set_styles():
    # Set matplotlib styles
    pass

def retrieve_data_cedar():

    with open('../.secrets.json') as secrets:
        cedar_api_key = json.load(secrets)["authkey_RENS"]
    
    print(json.load(secrets))

    print(cedar_api_key)

def main():
    retrieve_data_cedar()

if __name__ == '__main__':
    main()

