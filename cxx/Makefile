CXX = g++
CXXFLAGS = -g -O3 -std=c++0x
LDFLAGS =
LIBS = -lcurl -ljsoncpp -lpthread

all: phd2client

guider.o: guider.cpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<

phd2client: phd2client.o guider.o
	$(CXX) $(LDFLAGS) -o $@ $^ $(LIBS)

phd2client.o: phd2client.cpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<

clean:
	rm -f phd2client *.o core
