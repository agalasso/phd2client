/*

MIT License

Copyright (c) 2017 Andy Galasso

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

*/

#ifndef GUIDER_INCLUDED
#define GUIDER_INCLUDED

#include <jsoncpp/json/json.h>
#include <string>
#include <vector>

// settling progress information returned by Guider::CheckSettling()
struct SettleProgress
{
    bool Done;
    double Distance;
    double SettlePx;
    double Time;
    double SettleTime;
    int Status;
    std::string Error;
};

// guiding statistics information returned by Guider::GetStats()
struct GuideStats
{
    double rms_tot;
    double rms_ra;
    double rms_dec;
    double peak_ra;
    double peak_dec;
};

// Guider - a C++ wrapper for the PHD2 server API
//    https://github.com/OpenPHDGuiding/phd2/wiki/EventMonitoring
//
class Guider
{
    class Impl;
    Impl *m_rep;

    Guider(const Guider&) = delete;
    Guider& operator=(const Guider&) = delete;

public:

    // the constuctor takes the host name an instance number for the PHD2 server.
    // Call Connect() to establish the connection to PHD2.
    Guider(const char *hostname, unsigned int phd2_instance = 1);

    // The destructor will disconnect from PHD2
    ~Guider();

    // when any of the API methods below fail they will return false, and additional 
    // error information can be retrieved by calling LastError()
    const std::string& LastError() const;

    // connect to PHD2 -- you'll need to call Connect before calling any of the server API methods below
    bool Connect();

    // disconnect from PHD2. The Guider destructor will do this automatically.
    void Disconnect();

    // these two member functions are for raw JSONRPC method invocation. Generally you won't need to
    // use these functions as it is much more convenient to use the higher-level methods below
    Json::Value Call(const std::string& method);
    Json::Value Call(const std::string& method, const Json::Value& params);

    // Start guiding with the given settling parameters. PHD2 takes care of looping exposures,
    // guide star selection, and settling. Call CheckSettling() periodically to see when settling
    // is complete.
    bool Guide(double settlePixels, double settleTime, double settleTimeout);

    // Dither guiding with the given dither amount and settling parameters. Call CheckSettling()
    // periodically to see when settling is complete.
    bool Dither(double ditherPixels, double settlePixels, double settleTime, double settleTimeout);

    // Check if phd2 is currently in the process of settling after a Guide or Dither
    bool IsSettling(bool *val);

    // Get the progress of settling
    bool CheckSettling(SettleProgress *s);

    // Get the guider statistics since guiding started. Frames captured while settling is in progress
    // are excluded from the stats.
    bool GetStats(GuideStats *stats);

    // stop looping and guiding
    bool StopCapture(unsigned int timeoutSeconds = 10);

    // start looping exposures
    bool Loop(unsigned int timeoutSeconds = 10);

    // get the guider pixel scale in arc-seconds per pixel
    bool PixelScale(double *result);

    // get a list of the Equipment Profile names
    bool GetEquipmentProfiles(std::vector<std::string> *profiles);

    // connect the equipment in an equipment profile
    bool ConnectEquipment(const char *profileName);

    // disconnect equipment
    bool DisconnectEquipment();

    // get the AppState (https://github.com/OpenPHDGuiding/phd2/wiki/EventMonitoring#appstate)
    // and current guide error
    bool GetStatus(std::string *appState, double *avgDist);

    // check if currently guiding
    bool IsGuiding(bool *result);

    // pause guiding (looping exposures continues)
    bool Pause();

    // un-pause guiding
    bool Unpause();

    // save the current guide camera frame (FITS format), returning the name of the file in *filename.
    // The caller will need to remove the file when done.
    bool SaveImage(std::string *filename);
};

#endif // GUIDER_INCLUDED
