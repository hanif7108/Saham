import pandas as pd

# Daftar 75 saham syariah paling likuid di BEI (JII70 + ISSI Bluechips)
sharia_stocks = [
    "ACES", "ADMR", "ADRO", "AKRA", "AMMN", "ANTM", "ARTO", "ASII", "ASRI", "AUTO",
    "BFIN", "BMTR", "BRIS", "BRMS", "BRPT", "BSDE", "BUKA", "BUMI", "CPIN", "CTRA",
    "DEWA", "DOID", "ELSA", "EMTK", "ENRG", "ERAA", "ESSA", "EXCL", "FILM", "GOTO",
    "HEAL", "HRUM", "ICBP", "INCO", "INDF", "INDY", "INKP", "INTP", "ISAT", "ITMG",
    "JPFA", "KLBF", "KPIG", "LSIP", "MAPA", "MAPI", "MDKA", "MEDC", "MIKA", "MNCN",
    "MTEL", "MYOR", "PGAS", "PGEO", "PTBA", "PTPP", "PWON", "SCMA", "SIDO", "SILO",
    "SMGR", "SMRA", "TAPG", "TINS", "TKIM", "TLKM", "TPIA", "UNTR", "UNVR", "WIKA",
    "WSKT", "WTON", "BTPS", "MTDL", "MARK"
]

df = pd.DataFrame({"Ticker": sorted(sharia_stocks)})
df.to_csv('/Users/hanif/Saham/daftar_saham_syariah.csv', index=False)
print(f"Berhasil memperbarui daftar dengan {len(sharia_stocks)} saham syariah likuid!")
