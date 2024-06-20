from rdflib import Namespace
from rdflib.namespace import XSD, RDF
from rdflib.plugins.sparql import prepareQuery


def process_simple_query(graph, query_string):
    ti = Namespace("https://github.com/RenVit318/financial_dashboard/blob/main/code/vocab/transaction_info.ttl#")
    query = prepareQuery(query_string, initNs={"ti": ti, "xsd": XSD})
    res = graph.query(query)

    return res