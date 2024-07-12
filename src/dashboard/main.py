import matplotlib.pyplot as plt

import json
import requests
from urllib import parse

from rdflib import Graph
from rdflib.plugins.sparql import prepareQuery
from rdflib import Namespace
import streamlit as st

from plotting import plot_bp, plot_fitbit
from auth import setup_authenticator


def set_styles():
    # Set matplotlib styles
    plt.style.use('bmh')

@st.cache_data
def retrieve_data_cedar():
    #st.write("Retrieving data now...")
    try:
        g = Graph()
        g.parse('mock_data.ttl')
        return g
    except FileNotFoundError:
        print("No existing file discovered. Starting data import from CEDAR..")
    
    with open('../.secrets.json') as secrets:
        cedar_api_key = json.load(secrets)["authkey_RENS"]

    # Right now, we get the URIs of all instances in the mock_data folder and then separately query and parse each file
    # Is there a more efficient method to do this? e.g. query all contents within a folder at the same time with /folders/{folder_id}/contents_extract ???
    url = "https://resource.metadatacenter.org/folders/https%3A%2F%2Frepo.metadatacenter.org%2Ffolders%2F422ba135-4215-433a-b2d2-1d9a3fee7317/contents" 
    headers = {"accept": "application/json", "authorization": cedar_api_key}
    response = requests.get(url, headers=headers)
    response = response.json()

    # Make an RDFlib Graph on which we can query for the dashboard
    g = Graph()
    patients = [] # Keep track of which patients have been added to the graph

    # Request each instance individually and add it to the graph
    cedar_instances = response["resources"]
    N = len(cedar_instances)
    print(f"Found {N} instances to import. (Corresponding to {N//2} data entries.)")
    for i, instance in enumerate(cedar_instances):
        instance_ID = parse.quote_plus(instance["@id"]) # make the instance ID url-safe

        # Send out get request for instance data
        url = "https://resource.metadatacenter.org/template-instances/" + instance_ID
        #print(url)
        
        response = requests.get(url, headers=headers)

        # Import data
        instance_data = response.json()
        g.parse(data=instance_data, format='json-ld')

        # Try import patient information, if it hasn't been done yet
        try:
            # This is not the fastest method, but data is cached anywho. Speed up?
            print("Checking Patient ID")
            patient_reg_ID = instance_data["Patient"]["@id"]
            if patient_reg_ID in patients:
                print("patient ID already included")
                patient_reg_ID = None
        except KeyError:
            patient_reg_ID = None

        if patient_reg_ID is not None: # Do this for error catching
            print("patient ID not yet included")
            patients.append(patient_reg_ID)
            patient_reg_ID = parse.quote_plus(patient_reg_ID)
            patient_url = "https://resource.metadatacenter.org/template-instances/" + patient_reg_ID
            patient_response = requests.get(patient_url, headers=headers)
            patient_data = patient_response.json()
            print(patient_data)
            g.parse(data=patient_data, format='json-ld')

        


        print(f'Finished import instance {i+1}/{N}')#, end='\r')

    g.serialize(format='ttl', destination='mock_data.ttl')
    print('Completed.\n\n')

    return g

def get_patient_list(g):
    query_str = """
        PREFIX pghdc: <https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/>
        SELECT ?id
        WHERE {
            ?x pghdc:patientID ?id .
        }
    """
    pghdc = Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/")
    query = prepareQuery(query_str, initNs={"pghdc": pghdc})
    res = g.query(query)
    
    patients = []
    for row in res:
        patients.append(row.id.value)
    return patients

def setup_sidebar(patients):
    plot_attrs = {}

    # Sidebar patient selector
    plot_attrs["patient"] = st.sidebar.selectbox("Select a Patient ID", patients)

    # Sidebar plot attribute selector
    st.sidebar.write("Tick the boxes of the attributes you want to see plotted below.")
    st.sidebar.write("")
    
    st.sidebar.write("Blood Pressure Values")
    plot_attrs["pulse"]  =  st.sidebar.checkbox("Pulse Rate")
    plot_attrs["sys_bp"] =  st.sidebar.checkbox("Systolic Blood Pressure")
    plot_attrs["dia_bp"] =  st.sidebar.checkbox("Diastolic Blood Pressure")

    st.sidebar.write("")
    st.sidebar.write("Fitbit Values")
    plot_attrs["rest_heartrate"] = st.sidebar.checkbox("Resting Heart Rate") 
    plot_attrs["activity"]       = st.sidebar.checkbox("Activity") 
    plot_attrs["steps_count"]    = st.sidebar.checkbox("Step Count") 
    plot_attrs["sleep_data"]     = st.sidebar.checkbox("Sleep Data") 
    
    return plot_attrs




def main(): 
    authenticator = setup_authenticator()
    name, authentication_status, username = authenticator.login(location='main')

    set_styles()

    if st.session_state["authentication_status"] is False:
        st.error('Username/password is incorrect')
    if st.session_state["authentication_status"] is None:
        st.warning('Please enter your username and password')
    elif st.session_state["authentication_status"]:
        authenticator.logout()
        st.write(f'Welcome *{st.session_state["name"]}* to the PGHD dashboard')

    
        # Go into the true content
        g = retrieve_data_cedar()
        patients = get_patient_list(g)
        patients.append('0000')

        plot_attrs = setup_sidebar(patients)
        st.write(f"You are now looking at the data of Patient {plot_attrs['patient']}")
        if plot_attrs["pulse"] or plot_attrs["sys_bp"] or plot_attrs["dia_bp"]:
            plot_bp(g, plot_attrs)    

        # Fitbit plotter handlers - separated out because of the different orders of magnitude
        if plot_attrs["rest_heartrate"]:
            plot_fitbit(g, plot_attrs) 
        if plot_attrs["activity"]:
            plot_fitbit(g, plot_attrs)     
        if plot_attrs["steps_count"]:
            plot_fitbit(g, plot_attrs) 
        if plot_attrs["sleep_data"]:
            plot_fitbit(g, plot_attrs)     



if __name__ == '__main__':
    main()

