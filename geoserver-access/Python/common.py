
def open_xml_request_template(req_file):
    """Open and read the XML request template from a file in requests directory."""
    with open(f"../requests/{req_file}", 'r') as file:
        return file.read()