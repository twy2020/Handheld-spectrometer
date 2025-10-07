# Spectrometer Data Analysis for *Pseudomonas aeruginosa* Culture

## Project Overview
This project involves the analysis of spectral data obtained from a 96-well plate culture substrate of *Pseudomonas aeruginosa*. Measurements were conducted using a Handheld Spectrometer over a total period of 9 hours. The data from the latter ~6 hours (recorded at one-minute intervals) was retained for detailed analysis.

## Files in `sample_data`

The `sample_data` directory contains three primary files:

1.  **`measurement_session_20251005_153547.csv`**
    *   This file contains the raw data captured by our in-house developed Handheld Spectrometer and its accompanying host computer software.

2.  **`process.py`**
    *   This is a specialized Python script designed for filtering the spectral data and generating plots/charts.

3.  **`result.png`**
    *   This figure presents a comparative analysis of the substrate spectral change curves, measured under three different illumination modes: **ONLY LED**, **ONLY UV**, and **LED_UV**.

## Known Issues & Notes
We identified a synchronization issue in the device's timed measurement mechanism. Some repeated measurements returned values of zero, which is attributed to a lack of synchronization with the light source.

Despite this issue, observable patterns can still be discerned from the extensive set of redundant measurement data.