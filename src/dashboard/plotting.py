import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from datetime import date

from rdflib import Namespace
from rdflib.namespace import XSD, RDF
from rdflib.plugins.sparql import prepareQuery



def process_simple_query(graph, query_string):
    ti = Namespace("https://github.com/RenVit318/financial_dashboard/blob/main/code/vocab/transaction_info.ttl#")
    query = prepareQuery(query_string, initNs={"ti": ti, "xsd": XSD})
    res = graph.query(query)

    return res



def plot_history(g, atts_to_plot):

    query_str = """
        PREFIX pghdc: <https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/>
        PREFIX smash: <http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX dc: <http://purl.org/dc/elements/1.1/>
        SELECT ?pulse ?sys_bp ?dia_bp ?date
        WHERE {
            ?y pghdc:patient ?x ;
               pghdc:collected_PGHD ?z . 
            ?x pghdc:patientID "1234"^^xsd:int .
            ?z smash:hasSystolicBloodPressureValue ?sys_bp ;
               smash:hasDiastolicBloodPressureValue ?dia_bp ;
               smash:hasPulseRate ?pulse ;
               dc:date ?date .
        }
    """
    pghdc = Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/")
    smash = Namespace("http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#")
    dc    = Namespace("http://purl.org/dc/elements/1.1/")
    query = prepareQuery(query_str, initNs={"pghdc": pghdc, "smash": smash, "dc": dc, "xsd": XSD})
    res = g.query(query)

    N = len(res)
    data = pd.DataFrame({
        'date'  : np.zeros(N, dtype=object),
        'pulse' : np.zeros(N, dtype=float),
        'sys_bp': np.zeros(N, dtype=float),
        'dia_bp': np.zeros(N, dtype=float),
    })

    for i, row in enumerate(res):
        data.loc[i, 'date']   = date.fromisoformat(row.date)
        data.loc[i, 'pulse']  = float(row.pulse)
        data.loc[i, 'sys_bp'] = float(row.sys_bp)
        data.loc[i, 'dia_bp'] = float(row.dia_bp)

    unique_dates, idxs = np.unique(data['date'], return_index=True)
    extremes = (np.min(unique_dates), np.max(unique_dates))

    daterange = st.slider(label='Select date range', min_value=extremes[0], max_value=extremes[1],
                          value=extremes)

    # Plotting
    fig = plt.figure(figsize=(8,5))

    # Can we do this in a way that properly makes use of pd data frames?
    if atts_to_plot['pulse']:
        plt.scatter(data.loc[idxs, 'date'], data.loc[idxs, 'pulse'],
                    lw=1, ls='--', label='Pulse Rate')
    if atts_to_plot['sys_bp']:
        plt.scatter(data.loc[idxs, 'date'], data.loc[idxs, 'sys_bp'],
                    lw=1, ls='--', label='Systolic BP')
    if atts_to_plot['dia_bp']:
        plt.scatter(data.loc[idxs, 'date'], data.loc[idxs, 'dia_bp'],
                    lw=1, ls='--', label='Diastolic BP')
        
    plt.axhline(y=0, lw=1)

    plt.xlim(daterange)
    plt.xticks(rotation=60)
    
    plt.ylabel('Y')
    plt.legend(loc='lower right')
    st.write(fig)
