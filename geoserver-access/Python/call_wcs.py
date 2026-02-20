import requests
import getpass
import common


def call_wcs_service(body, output_file="output.tiff"):
    url = "https://geoserver.p.niva.no/wcs"
    headers = {
        "Content-Type": "application/xml",
    }
    response = requests.post(url, data=body, headers=headers, auth=(username, password))
    
    # Check if the request was successful
    if response.status_code == 200:
        # Save the response content as a TIFF file
        with open(output_file, 'wb') as f:
            f.write(response.content)
        print(f"TIFF file saved successfully as: {output_file}")
        return output_file
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
        return None

xml_body = common.open_xml_request_template("wcs_getcoverage.xml")
minx = -340648
maxx = 1077651
miny = 6227234
maxy = 8157359
xml_body = xml_body.replace("{{minx}}", str(minx)).replace("{{maxx}}", str(maxx)).replace("{{miny}}", str(miny)).replace("{{maxy}}", str(maxy))
username = getpass.getpass(prompt="Username: ")
password = getpass.getpass(prompt="Password: ")
call_wcs_service(xml_body, output_file="dem_area.tiff")