import pyvisa

rm = pyvisa.ResourceManager()
resources = rm.list_resources()

print("Available VISA resources:")
for resource in resources:
    try:
        # Try to open each resource and get its ID
        inst = rm.open_resource(resource)
        # Query the device identification
        idn = inst.query("*IDN?")
        print(f"Resource: {resource}")
        print(f"Device ID: {idn}")
        inst.close()
    except:
        print(f"Resource: {resource} (Could not query device)")
    print("-" * 50)
