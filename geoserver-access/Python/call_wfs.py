import requests
import getpass
import common
import re


def call_wfs_service(body, output_file="output.geojson"):
    url = "https://geoserver.p.niva.no/wfs"
    headers = {
        "Content-Type": "application/xml",
    }
    response = requests.post(url, data=body, headers=headers, auth=(username, password))
    
    # Check if the request was successful
    if response.status_code == 200:
        # Save the response content as a GeoJSON file
        with open(output_file, 'wb') as f:
            f.write(response.content)
        print(f"GeoJSON file saved successfully as: {output_file}")
        return output_file
    else:
        print(f"Error: {response.status_code}")
        exception_text = re.search(r'<ows:ExceptionText>(.*?)</ows:ExceptionText>', response.text)
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

username = getpass.getpass(prompt="Username: ")
password = getpass.getpass(prompt="Password: ")
xml_template = common.open_xml_request_template("wfs_getfeature_kommune.xml")

KOMMUNER = [
    "1515",
    "1516",
    "1520",
    "1577",
    "1508",
    "1532",
    "1514",
    "1531",
    "1580",
    "1528",
    "1517",
    "1511",
]

# Build the filter and inject it into the XML template
filter_xml = build_filter_xml(KOMMUNER)
xml_body = xml_template.replace("{{filter}}", filter_xml)

call_wfs_service(xml_body, output_file="kommune.geojson")
