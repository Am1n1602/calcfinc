"""Loaders: get facts into a store from records, CSV files or DataFrames."""
from calcfinc.loaders.csv import load_csv, read_rows
from calcfinc.loaders.dataframe import frame_source, frame_to_rows
from calcfinc.loaders.records import LoadError, LoadReport, load_records

__all__ = ["LoadError", "LoadReport", "frame_source", "frame_to_rows", "load_csv", "load_records", "read_rows"]
