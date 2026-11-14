import { describe, expect, it } from 'vitest';
import { parseCoordPairs } from './geo';

describe('parseCoordPairs', () => {
  it('reads two latitude,longitude pairs separated by spaces or commas', () => {
    expect(parseCoordPairs('18.37, 77.435  18.41, 77.46')).toEqual([
      { latitude_deg: 18.37, longitude_deg_east: 77.435 }, { latitude_deg: 18.41, longitude_deg_east: 77.46 }]);
    expect(parseCoordPairs('18.37 77.435 18.41 77.46')?.length).toBe(2);
  });
  it('honours hemisphere letters and wraps longitude', () => {
    expect(parseCoordPairs('10S 20W')).toEqual([{ latitude_deg: -10, longitude_deg_east: -20 }]);
    expect(parseCoordPairs('0 190')?.[0].longitude_deg_east).toBe(-170);
  });
  it('rejects odd counts and out-of-range latitude', () => {
    expect(parseCoordPairs('18.37 77.435 18.41')).toBeNull();
    expect(parseCoordPairs('95 10')).toBeNull();
    expect(parseCoordPairs('hello')).toBeNull();
  });
});
