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
CLIENT_ID = '23RGC3' 
CLIENT_SECRET = '14de2f34d59a224fe4f0a4635de46360'
# cedar_url = 'https://resource.metadatacenter.org/template-instances'
# cedar_api_key = 'apiKey f1b9368fb41c87452d4a6d65524bde5137870db4ec456d6882546ef8d427c183'


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
body = auth2_client.body(date=Start_time)
activities = auth2_client.activities(date=Start_time)
sleep = auth2_client.sleep(date=Start_time)
fat = body['body']['fat'] if 'fat' in body['body'] else 0
bmi = body['body']['bmi'] if 'bmi' in body['body'] else 0 
fairlyActiveMinutes = activities['summary']['fairlyActiveMinutes'] if 'fairlyActiveMinutes' in activities['summary'] else 0
lightlyActiveMinutes = activities['summary']['lightlyActiveMinutes'] if 'lightlyActiveMinutes' in activities['summary'] else 0
sedentaryMinutes = activities['summary']['sedentaryMinutes'] if 'sedentaryMinutes' in activities['summary'] else 0
veryActiveMinutes = activities['summary']['veryActiveMinutes'] if 'veryActiveMinutes' in activities['summary'] else 0
if len(sleep['sleep']) > 0:
    sleep_duration = sleep['sleep'][0]['duration'] if 'duration' in sleep['sleep'][0] else 0
else:
    sleep_duration = 0
if len(sleep['sleep']) > 0:
    sleep_efficiency = sleep['sleep'][0]['duration'] if 'efficiency' in sleep['sleep'][0] else 0
else:
    sleep_efficiency = 0
restingHeartRate = activities['summary']['restingHeartRate'] if 'restingHeartRate' in activities['summary'] else 0
Total_distances = activities['summary']['distances'][0]['distance'] if 'distances' in activities['summary'] else 0
calories_burnt = activities['summary']['caloriesOut'] if 'caloriesOut' in activities['summary'] else 0
steps_count = activities['summary']['steps'] if 'steps' in activities['summary'] else 0

# COMMENT BY RK: Typo in function name
def puish_data_to_cedar():
    cedar_url = 'https://resource.metadatacenter.org/template-instances'
    cedar_api_key = 'apiKey 62838dcb5b6359a1a93baeeef907669813ec431437b168efde17a61c254b3355'
    
#push data to CEDAR 
    cedar_template = open('templates/fitbit_template.json')
    data = json.load(cedar_template)
    #data['userid']['@value'] = CLIENT_ID # COMMENT BY RK: This should be moved to the registration step and checked against for authentication.

    data['Fat']['@value'] = str(fat)
    data['BMI']['@value'] = str(bmi)
    #data['date time']['@value'] =Start_time.strftime('%Y-%m-%dT%H:%M:%S') # COMMENT BY RK: Can we get the observation time from the fitbit? According to the description it should also only be date.
    data['Fairly active minutes']['@value'] = str(fairlyActiveMinutes)
    data['Lightly active minutes']['@value'] = str(lightlyActiveMinutes)
    data['Sedentary minutes']['@value'] = str(sedentaryMinutes)
    data['Very active minutes']['@value'] = str(veryActiveMinutes)
    data['Sleep duration']['@value'] = str(sleep_duration)
    data['Sleep efficiency']['@value'] = str(sleep_efficiency)
    data['Resting heart rate']['@value'] = str(restingHeartRate)
    data['Steps']['@value'] = str(steps_count)

    # data['schema:name'] = f'VHD {Start_time}' ##VHD 2023-11-14 00:00:00

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
        else:
            print(f"Error: {response.status_code}, {response.text},{Start_time}")
            msg =  f"Error: {response.status_code}, {response.text},  "

    except Exception as e:
        # print(f"An error occurred: {e},{Start_time}")
        msg = f"An error occurred: {e},  "

    # COMMENT BY RK: Somewhere here add the PGHD_CONNECT push code. i.e. get the data instance URI, combine it with Patient URI (which should have been gotten at the authentication step
    # and then POST an instance of PGHD_CONNECT with these values and fitbit as source_of_PGHD
    
    return response, msg

response,msg   = puish_data_to_cedar()
print(msg)
print(response.status_code)

#TODO 
# 1. fix the gather_keys_oauth2 importation error 

