import streamlit as st
import mpld3
from mpld3 import plugins
import streamlit.components.v1 as components

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from datetime import date

from rdflib import Namespace
from rdflib.namespace import XSD, RDFS
from rdflib.plugins.sparql import prepareQuery


def process_simple_query(graph, query_string):
    ti = Namespace("https://github.com/RenVit318/financial_dashboard/blob/main/code/vocab/transaction_info.ttl#")
    query = prepareQuery(query_string, initNs={"ti": ti, "xsd": XSD})
    res = graph.query(query)

    return res



def plot_history(g, atts_to_plot):
    query_str = """
        PREFIX pghdc: <https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/>
        PREFIX bp_aux: <https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/>
        PREFIX smash: <http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX dc: <http://purl.org/dc/elements/1.1/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pulse ?sys_bp ?dia_bp ?date ?loc ?person ?pos
        WHERE {
            ?y pghdc:patient ?x ;
               pghdc:collected_PGHD ?z . 
            ?x pghdc:patientID "1234"^^xsd:int .
            ?z smash:hasSystolicBloodPressureValue ?sys_bp ;
               smash:hasDiastolicBloodPressureValue ?dia_bp ;
               smash:hasPulseRate ?pulse ;
               bp_aux:CollectionLocation ?loc_uri ;
               bp_aux:CollectionPerson ?person_uri ;
               bp_aux:CollectionPosition ?pos_uri ;
               dc:date ?date .

            ?loc_uri    rdfs:label ?loc .
            ?person_uri rdfs:label ?person .
            ?pos_uri    rdfs:label ?pos .
        }
    """
    pghdc = Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/")
    smash = Namespace("http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#")
    dc    = Namespace("http://purl.org/dc/elements/1.1/")
    bp_aux= Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/")
    query = prepareQuery(query_str, initNs={"pghdc": pghdc, "bp_aux": bp_aux, "smash": smash, "dc": dc, "xsd": XSD, "rdfs": RDFS})
    res = g.query(query)

    N = len(res)
    data = pd.DataFrame({
        'date'  : np.zeros(N, dtype=object),
        'pulse' : np.zeros(N, dtype=float),
        'sys_bp': np.zeros(N, dtype=float),
        'dia_bp': np.zeros(N, dtype=float),
        'loc'   : np.zeros(N, dtype=str),
        'person': np.zeros(N, dtype=str),
        'pos'   : np.zeros(N, dtype=str),
    })

    for i, row in enumerate(res):
        data.loc[i, 'date']   = date.fromisoformat(row.date)
        data.loc[i, 'pulse']  = float(row.pulse)
        data.loc[i, 'sys_bp'] = float(row.sys_bp)
        data.loc[i, 'dia_bp'] = float(row.dia_bp)
        data.loc[i, 'loc']    = row.loc
        data.loc[i, 'person'] = row.person
        data.loc[i, 'pos']    = row.pos

    unique_dates, idxs = np.unique(data['date'], return_index=True)
    extremes = (np.min(unique_dates), np.max(unique_dates))

    daterange = st.slider(label='Select date range', min_value=extremes[0], max_value=extremes[1],
                          value=extremes)

    # Plotting
    fig = plt.figure()#figsize=(8,5))

    # Can we do this in a way that properly makes use of pd data frames?
    if atts_to_plot['pulse']:
        plt.plot(data.loc[idxs, 'date'], data.loc[idxs, 'pulse'],
                 lw=0, marker='.', label='Pulse Rate')
    if atts_to_plot['sys_bp']:
        plt.plot(data.loc[idxs, 'date'], data.loc[idxs, 'sys_bp'],
                 lw=0, marker='.', label='Systolic BP')
    if atts_to_plot['dia_bp']:
        plt.plot(data.loc[idxs, 'date'], data.loc[idxs, 'dia_bp'],
                 lw=0, marker='.', label='Diastolic BP')
        
    #plt.axhline(y=0, lw=1)

    #plt.xlim(daterange)
    #plt.xticks(rotation=60)
    
    #plt.ylabel('Y')




    plt.legend(loc='lower right')
    css = """
    table
    {
    border-collapse: collapse;
    }
    th
    {
    color: #ffffff;
    background-color: #000000;
    }
    td
    {
    background-color: #cccccc;
    }
    table, th, td
    {
    font-family:Arial, Helvetica, sans-serif;
    border: 1px solid white;
    text-align: right;
    }
    """




    for axes in fig.axes:
        for line in axes.get_lines():

            labels = []

            for i in range(N):
                html_label = f'<table border="1" class="dataframe"> <thead> <tr style="text-align: right;"> </thead> <tbody> <tr> <th>Position</th> <td>{data.loc[i, "pos"]}</td> </tr> <tr> <th>Person</th> <td>{data.loc[i, "person"]}</td> </tr> <tr> <th>Location</th> <td>{data.loc[i, "loc"]}</td> </tr> </tbody> </table>'
                labels.append(html_label)

            # Create the tooltip with the labels (x and y coords) and attach it to each line with the css specified
            tooltip = plugins.PointHTMLTooltip(line, labels, css=css)
            # Since this is a separate plugin, you have to connect it
            plugins.connect(fig, tooltip)

    #        print(line)
    #        # get the x and y coords
    #        xy_data = line.get_xydata()
    #        labels = []
    #        for x, y in xy_data:
    #            # Create a label for each point with the x and y coords
    #            html_label = f'<table border="1" class="dataframe"> <thead> <tr style="text-align: right;"> </thead> <tbody> <tr> <th>x</th> <td>{x}</td> </tr> <tr> <th>y</th> <td>{y}</td> </tr> </tbody> </table>'
    #            labels.append(html_label)
    #        # Create the tooltip with the labels (x and y coords) and attach it to each line with the css specified
    #        tooltip = plugins.PointHTMLTooltip(line, labels, css=css)
    #        # Since this is a separate plugin, you have to connect it
    #        plugins.connect(fig, tooltip)

    fig_html = mpld3.fig_to_html(fig)
    components.html(fig_html, height=600)
    



