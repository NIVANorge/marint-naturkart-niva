from requests.auth import HTTPBasicAuth
import requests
import re
import getpass
    
geoserver_auth = None

def login():
    """Login to Geoserver and store the authentication for future requests."""
    global geoserver_auth
    if geoserver_auth is not None:
        print("Already logged in.")
        return
    username = getpass.getpass(prompt="Username: ")
    password = getpass.getpass(prompt="Password: ")
    geoserver_auth = HTTPBasicAuth(username, password)

def fetch_kommuner(kommuner_list):
    xml_template = """
        <Query typeNames="no.niva.nkm:kommune_simplified">
            {{filter}}
        </Query>
    """
    filter_xml = build_filter_xml(kommuner_list)
    query = xml_template.replace("{{filter}}", filter_xml)
    return call_wfs_service(query)

def fetch_bunnsedimenter_kornstorrelse(bbox):
    xml_template = """
        <Query typeNames="no.niva.nkm:nkm_kornstorrelse_f">
            <fes:Filter>
                <fes:BBOX>
                    <fes:ValueReference>geom</fes:ValueReference>
                    <gml:Envelope srsName="EPSG:25833">
                        <gml:lowerCorner>{{minx}} {{miny}}</gml:lowerCorner>
                        <gml:upperCorner>{{maxx}} {{maxy}}</gml:upperCorner>
                    </gml:Envelope>
                </fes:BBOX>
            </fes:Filter>
        </Query>
    """
    query = xml_template.replace("{{minx}}", str(bbox[0])) \
                        .replace("{{miny}}", str(bbox[1])) \
                        .replace("{{maxx}}", str(bbox[2])) \
                        .replace("{{maxy}}", str(bbox[3]))
    return call_wfs_service(query)

def call_wfs_service(query_xml):
    url = "https://geoserver.p.niva.no/wfs"
    headers = {
        "Content-Type": "application/xml",
    }
    body = """<?xml version="1.0" encoding="UTF-8"?>
                <GetFeature version="2.0.0" service="WFS" outputFormat="application/json"
                    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
                    xmlns="http://www.opengis.net/wfs/2.0" 
                    xmlns:ows="http://www.opengis.net/ows/1.1" 
                    xmlns:gml="http://www.opengis.net/gml/3.2" 
                    xmlns:fes="http://www.opengis.net/fes/2.0"
                    xsi:schemaLocation="http://www.opengis.net/wfs/2.0 https://schemas.opengis.net/wfs/2.0/wfs.xsd">
                {{query}}
            </GetFeature>
        """.replace("{{query}}", query_xml)
    if geoserver_auth is None:
        login()
    response = requests.post(url, data=body, headers=headers, auth=geoserver_auth)
    print(f"Response content type: {response.headers.get('Content-Type', '')}")
    # Check if the request was successful
    if response.status_code == 200 and response.headers.get("Content-Type", "").startswith("application/json"):
        return response.json()
    else:
        print(f"Error: {response.status_code}")
        exception_text = re.search(r'<ows:ExceptionText>(.*?)</ows:ExceptionText>', response.text, re.DOTALL)
        if exception_text:
            print(f"Exception: {exception_text.group(1)}")
        return None
    
def build_filter_xml(kommuner_list):
    """Build OGC Filter Encoding XML for IN query"""
    if not kommuner_list:
        return ""
    
    if len(kommuner_list) == 1:
        return f"""<fes:Filter>
      <fes:PropertyIsEqualTo>
        <fes:ValueReference>kommunenummer</fes:ValueReference>
        <fes:Literal>{kommuner_list[0]}</fes:Literal>
      </fes:PropertyIsEqualTo>
    </fes:Filter>"""
    
    conditions = "\n      ".join([
        f"""<fes:PropertyIsEqualTo>
        <fes:ValueReference>kommunenummer</fes:ValueReference>
        <fes:Literal>{k}</fes:Literal>
      </fes:PropertyIsEqualTo>""" for k in kommuner_list
    ])
    
    return f"""<fes:Filter>
      <fes:Or>
      {conditions}
      </fes:Or>
    </fes:Filter>"""
