#include "../tests/tests.h"

using namespace std;

void Tests::runAnalysisBoundsTests() {
  cout << "Running AnalysisBounds tests" << endl;

  AnalysisBounds bounds = {2, 3, 5, 8};

  // Test corners
  assert(bounds.contains(2, 3));
  assert(bounds.contains(5, 8));
  assert(bounds.contains(2, 8));
  assert(bounds.contains(5, 3));

  // Test middle
  assert(bounds.contains(3, 5));

  // Test outside
  assert(!bounds.contains(1, 3));
  assert(!bounds.contains(2, 2));
  assert(!bounds.contains(6, 8));
  assert(!bounds.contains(5, 9));

  // Test Loc
  int xSize = 19;
  assert(bounds.contains(Location::getLoc(3, 5, xSize), xSize));
  assert(!bounds.contains(Location::getLoc(1, 3, xSize), xSize));
  assert(bounds.contains(Location::getLoc(2, 3, xSize), xSize));
  assert(bounds.contains(Location::getLoc(5, 8, xSize), xSize));

  cout << "AnalysisBounds tests passed!" << endl;
}
