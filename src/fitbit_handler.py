################ Fitbit_to_Cedar.py #############################
# PGHD Project
# Description: This script fetches the data from fitbit and pushes it to CEDAR
##################################################################

#importing libraries
from threading import current_thread
import gather_keys_oauth2 as Oauth2
import fitbit
import pandas as pd 
import datetime 
import json
import requests


# COMMENT BY RK: Question on execution of this code which impacts its structure. Is this always on, accepting incoming data POST requests when the fitbit is ready,
# or is it a script which we run on intervals through CRON jobs?

#fitbit credentials
Start_time =  datetime.now()
# COMMENT BY RK: Both of these need to be moved into a PGHD_REGISTRATION instance, and extracted dynamically in the fitbit_handler. 
# i.e. we have an incoming client ID + secret which we should check in the database if they match -> then match it to a Patient URI for PGHD_CONNECT
with open('secrets.json') as secrets:
    cedar_api_key = json.load(secrets)["authkey_RENS"]
with open('secrets.json') as secrets:
    CLIENT_ID = json.load(secrets)["CLIENT_ID"]
    # CLIENT_SECRET = json.load(secrets)["CLIENT_SECRET"]

with open('secrets.json') as secrets:
    CLIENT_SECRET = json.load(secrets)["CLIENT_SECRET"]
    
with open('secrets.json') as secrets:
    CEDAR_registration_ID = json.load(secrets)["CEDAR_registration_ID"]
    
print(CLIENT_ID)
print(CLIENT_SECRET)
print(CEDAR_registration_ID)
cedar_url = 'https://resource.metadatacenter.org/template-instances'



##fitbit authentication
def fitbit_authentication():
    server=Oauth2.OAuth2Server(CLIENT_ID, CLIENT_SECRET)
    server.browser_authorize()
    ACCESS_TOKEN=str(server.fitbit.client.session.token['access_token'])
    REFRESH_TOKEN=str(server.fitbit.client.session.token['refresh_token'])
    auth2_client=fitbit.Fitbit(CLIENT_ID,CLIENT_SECRET,oauth2=True,access_token=ACCESS_TOKEN,refresh_token=REFRESH_TOKEN)
    return auth2_client



auth2_client = fitbit_authentication()

# COMMENT BY RK: Is putting values to '0' if they do not exist right? This can mess with any statistics in the data I think. Make this None, or null I think
#Fetch data from Fitbit 
#TODO: put this in a function
start_time = datetime(2023, 11, 11)


def get_fitbit_data(start_time):
    body = auth2_client.body(date=start_time)
    activities = auth2_client.activities(date=start_time)
    sleep = auth2_client.sleep(date=start_time)
    fat = body['body']['fat'] if 'fat' in body['body'] else None
    bmi = body['body']['bmi'] if 'bmi' in body['body'] else None 
    fairlyActiveMinutes = activities['summary']['fairlyActiveMinutes'] if 'fairlyActiveMinutes' in activities['summary'] else None
    lightlyActiveMinutes = activities['summary']['lightlyActiveMinutes'] if 'lightlyActiveMinutes' in activities['summary'] else None
    sedentaryMinutes = activities['summary']['sedentaryMinutes'] if 'sedentaryMinutes' in activities['summary'] else None
    veryActiveMinutes = activities['summary']['veryActiveMinutes'] if 'veryActiveMinutes' in activities['summary'] else None
    if len(sleep['sleep']) > 0:
        sleep_duration = sleep['sleep'][0]['duration'] if 'duration' in sleep['sleep'][0] else None
    else:
        sleep_duration = None
    if len(sleep['sleep']) > 0:
        sleep_efficiency = sleep['sleep'][0]['duration'] if 'efficiency' in sleep['sleep'][0] else None
    else:
        sleep_efficiency = None
    restingHeartRate = activities['summary']['restingHeartRate'] if 'restingHeartRate' in activities['summary'] else None
    total_distances = activities['summary']['distances'][0]['distance'] if 'distances' in activities['summary'] else None
    calories_burnt = activities['summary']['caloriesOut'] if 'caloriesOut' in activities['summary'] else None
    steps_count = activities['summary']['steps'] if 'steps' in activities['summary'] else None
    
    fitbit_data = {
        "fat": fat,
        "bmi": bmi,
        "fairlyActiveMinutes": fairlyActiveMinutes,
        "lightlyActiveMinutes": lightlyActiveMinutes,
        "sedentaryMinutes": sedentaryMinutes,
        "veryActiveMinutes": veryActiveMinutes,
        "sleep_duration": sleep_duration,
        "sleep_efficiency": sleep_efficiency,
        "restingHeartRate": restingHeartRate,
        "total_distances": total_distances,
        "calories_burnt": calories_burnt,
        "steps_count": steps_count
    }

    return fitbit_data

# data = json.load(cedar_template)
def push_data_to_cedar(data, start_time, cedar_api_key,cedar_template,cedar_url):
    data = json.load(cedar_template)
    #data['userid']['@value'] = CLIENT_ID # COMMENT BY RK: This should be moved to the registration step and checked against for authentication.

    data['Fat']['@value'] = str(data.get("fat"))
    data['BMI']['@value'] = str(data.get("bmi"))
    data['Date']['@value'] =start_time.strftime('%Y-%m-%dT%H:%M:%S') # COMMENT BY RK: Can we get the observation time from the fitbit? According to the description it should also only be date.
    data['Fairly active minutes']['@value'] = str(data.get("fairlyActiveMinutes"))
    data['Lightly active minutes']['@value'] = str(data.get("lightlyActiveMinutes"))
    data['Sedentary minutes']['@value'] = str(data.get("sedentaryMinutes"))
    data['Very active minutes']['@value'] = str(data.get("veryActiveMinutes"))
    data['Sleep duration']['@value'] = str(data.get("sleep_duration"))
    data['Sleep efficiency']['@value'] = str(data.get("sleep_efficiency"))
    data['Resting heart rate']['@value'] = str(data.get("restingHeartRate"))
    # data['Total distance']['@value'] = str(data.get("total_distances"))
    # data['Calories burnt']['@value'] = str(data.get("calories_burnt"))
    data['Steps']['@value'] = str(data.get("steps_count"))
    
    cedar_template.close()
    

    

    #push data to cedar 
    # COMMENT BY RK: In production we should push to predefined folders so that things aren't lying around everywhere. 
    # you can do this by adding params = {'folder_id': folder_id} to the POST request below.
    try:
        response = requests.post(cedar_url, json=data, headers={'Content-Type': 'application/json',
                                                     'Accept': 'application/json',
                                                     'Authorization': cedar_api_key})
        if response.status_code == 201:  # Assuming a successful creation response
            # print(Start_time, "Data successfully pushed to Cedar!")
            msg = "Data successfully pushed to Cedar!"
            cedar_data_URI = response.json()["@id"]
        else:
            print(f"Error: {response.status_code}, {response.text},{start_time}")
            msg =  f"Error: {response.status_code}, {response.text},  "

    except Exception as e:
        # print(f"An error occurred: {e},{Start_time}")
        msg = f"An error occurred: {e},  "

    # COMMENT BY RK: Somewhere here add the PGHD_CONNECT push code. i.e. get the data instance URI, combine it with Patient URI (which should have been gotten at the authentication step
    # and then POST an instance of PGHD_CONNECT with these values and fitbit as source_of_PGHD
    
    return   msg, cedar_data_URI



def push_data_to_connect(cedar_data_URI,connect_template):
    # cedar_template_connect = open('connect.json')
    data = json.load(connect_template)

    data['Patient']['@id'] = str(meta_data['cedar_registration_URI'])
    data['collected_PGHD']['@id'] = cedar_data_URI
    data['source_of_PGHD']['@id'] = str(connect_ontology_prefix + 'bp_ivr')
    data['schema:name'] = 'temptest'

    
    
    try:
        response = requests.post(cedar_url, json=data, headers={'Content-Type': 'application/json',
                                                 'Accept': 'application/json',
                                                 'Authorization': cedar_api_key})
        if response.status_code == 201:  # Assuming a successful creation response
            msg = "Data successfully pushed to Cedar!"
        else:
            print(f"Error: {response.status_code}, {response.text},{start_time}")
            msg =  f"Error: {response.status_code}, {response.text},  "

    except Exception as e:
        msg = f"An error occurred: {e},  "
        
        
    return msg
#crerate main function to run all the functions and the script
def main():
    fitbit_data = get_fitbit_data(start_time)
    cedar_template = open('templates/fitbit_template.json')
    cedar_data_URI, fit_msg = push_data_to_cedar(fitbit_data, start_time, cedar_api_key,cedar_template,cedar_url)
    connect_template = open('templates/pghd_connect_template.json')
    connect_msg = push_data_to_connect(cedar_data_URI,connect_template)
    
    print(fit_msg)
    print(connect_msg)
    
if __name__ == "__main__":
    main()
#TODO 
# 1. fix the gather_keys_oauth2 importation error 

