# phd2client

A python binding for the PHD2 event server API.

## Installation

```
pip install phd2client
```

## Usage

```python
from phd2client.guider import Guider, GuiderException

with Guider("localhost", connect=True) as guider:
    try:
        # connect equipment in profile "Simulator"
        guider.ConnectEquipment("Simulator")

        # start guiding with settle tolerance of 2.0 pixels, 10 second settle time, 100-second timeout
        guider.Guide(2.0, 10.0, 100.0)
    except GuiderException as ex:
        print(f"Guider Error: {ex}")
```

See [phd2client.py](https://github.com/agalasso/phd2client/blob/master/python/examples/phd2client.py) for a more complete example.
