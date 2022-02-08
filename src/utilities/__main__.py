from sqlalchemy import create_engine, text

def main():
    engine = create_engine('psycopg+postgresql://mstatt:northforest@localhost/dbgen')
    with engine.connect() as conn:
        out =conn.execute(text('select 1'))
        for row in out:
            print(row[0])

if __name__ == '__main__':
    main()