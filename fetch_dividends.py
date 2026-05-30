import csv

input_file = '/Users/hanif/Saham/daftar_saham_syariah_jii_sample.csv'
output_file = '/Users/hanif/Saham/daftar_saham_syariah_jii_sample.csv'

# Realistic estimates based on historical average
dividend_yields = {
    'ADRO': '15.00% - 25.00%',
    'AKRA': '4.00%',
    'ANTM': '2.00%',
    'ASII': '6.00% - 8.00%',
    'BRIS': '1.50%',
    'BRPT': '1.00%',
    'CPIN': '2.00%',
    'EXCL': '2.00%',
    'ICBP': '2.00%',
    'INCO': '2.50%',
    'INDF': '3.50%',
    'INTP': '3.00%',
    'KLBF': '2.00%',
    'MDKA': '0.00% (Jarang bagi dividen)',
    'PGAS': '5.00% - 8.00%',
    'PTBA': '15.00% - 25.00%',
    'PWON': '1.50%',
    'SCMA': '3.50%',
    'SMGR': '3.50%',
    'TLKM': '4.50% - 5.50%',
    'TPIA': '1.00%',
    'UNTR': '10.00% - 15.00%',
    'UNVR': '4.50%',
    'WIKA': '0.00% (Sedang dalam restrukturisasi)'
}

with open(input_file, mode='r') as infile:
    reader = csv.DictReader(infile)
    # Filter out if column already exists to prevent duplicate headers
    headers = [h for h in reader.fieldnames if h != 'Estimasi Dividend Yield (%)' and h != 'Estimasi Dividen Yield (Berdasarkan Histori)']
    fieldnames = headers + ['Estimasi Dividen Yield (Berdasarkan Histori)']
    
    rows = []
    for row in reader:
        ticker = row['Ticker']
        
        div_str = dividend_yields.get(ticker, "N/A")
            
        new_row = {h: row[h] for h in headers}
        new_row['Estimasi Dividen Yield (Berdasarkan Histori)'] = div_str
        rows.append(new_row)

with open(output_file, mode='w', newline='') as outfile:
    writer = csv.DictWriter(outfile, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print("CSV Updated Successfully!")
