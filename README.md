# phd2client
Sample client code for PHD2 server API

### C++

dependencies:
  * [jsoncpp](https://github.com/open-source-parsers/jsoncpp)
  * [libcurl](https://curl.haxx.se/libcurl/)
  
```C++
#include "guider.h"

// instantiate a guider object that will connect to PHD2 running on "localhost"
Guider guider("localhost");

// connect to PHD2
bool ok = guider.Connect();
if (!ok)
    std::cerr << "could not connect to phd2: " << guider.LastError() << std::endl;

// connect gear in the equipment profile named Simulator
ok = guider.ConnectEquipment("Simulator");
if (!ok)
    std::cerr << "could not connect equipment: " << guider.LastError() << std::endl;

// start guiding with settle tolerance of 2.0 pixels, 10 second settle time, 100-second timeout
ok = guider.Guide(2.0, 10.0, 100.0);

```

See [phd2client.cpp](https://github.com/agalasso/phd2client/blob/master/cxx/phd2client.cpp) for a more complete example.

### C#

```C#
using guider;

...
    using (Guider guider = Guider.Factory("localhost"))
    {
        try
        {
            // connect to PHD2
            guider.Connect();

            // connect equipment in profile "Simulator"
            guider.ConnectEquipment("Simulator");

            // start guiding with settle tolerance of 2.0 pixels, 10 second settle time, 100-second timeout
            guider.Guide(2.0, 10.0, 100.0);
         }
         catch (GuiderException ex)
         {
             // Guider exception
             Console.WriteLine("Guider Error: {0}", ex.Message);
         }
    }
```

See [SampleClient.cs](https://github.com/agalasso/phd2client/blob/master/cs/PHD2Client/SampleClient.cs) for a more complete example.
