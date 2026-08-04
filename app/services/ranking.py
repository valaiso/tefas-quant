import pandas as pd
import sqlite3
import os
import json


def get_db_connection():
    base_dir = os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )

    db_path = os.path.join(base_dir, "tefas.db")

    return sqlite3.connect(
        db_path,
        check_same_thread=False
    )


def get_latest_score_date(conn):

    cur = conn.cursor()

    cur.execute(
        "SELECT MAX(date) FROM fund_scores"
    )

    result = cur.fetchone()

    return result[0] if result else None



def get_general_ranking(limit=100, conn=None):

    close_conn=False

    if conn is None:
        conn=get_db_connection()
        close_conn=True


    try:

        date=get_latest_score_date(conn)

        if not date:
            return pd.DataFrame()


        query="""

        SELECT

        s.fund_id,
        f.code,
        f.title,
        f.category,

        s.final_score,
        s.letter_grade,
        s.signal,

        s.category_rank,
        s.category_total,
        s.category_percentile,

        s.performance_score,
        s.risk_score,
        s.consistency_score,
        s.stability_score,

        s.breakdown_json,
        s.date


        FROM fund_scores s

        JOIN funds f
        ON s.fund_id=f.id


        WHERE s.date=?


        ORDER BY s.final_score DESC

        LIMIT ?

        """


        return pd.read_sql(
            query,
            conn,
            params=(date,limit)
        )


    finally:

        if close_conn:
            conn.close()



def get_category_ranking(category_name, conn=None):

    close_conn=False

    if conn is None:
        conn=get_db_connection()
        close_conn=True


    try:

        date=get_latest_score_date(conn)


        query="""

        SELECT

        s.fund_id,
        f.code,
        f.title,
        f.category,

        s.final_score,
        s.letter_grade,
        s.signal,

        s.category_rank,
        s.category_total,
        s.category_percentile


        FROM fund_scores s

        JOIN funds f
        ON s.fund_id=f.id


        WHERE s.date=?
        AND f.category=?


        ORDER BY s.final_score DESC

        """


        return pd.read_sql(
            query,
            conn,
            params=(date,category_name)
        )


    finally:

        if close_conn:
            conn.close()



def get_fund_detail_with_ranking(fund_id, conn=None):

    close_conn=False

    if conn is None:
        conn=get_db_connection()
        close_conn=True


    try:

        date=get_latest_score_date(conn)


        query="""

        SELECT

        s.*,

        f.code,
        f.title,
        f.category


        FROM fund_scores s


        JOIN funds f
        ON s.fund_id=f.id


        WHERE s.date=?
        AND s.fund_id=?

        """


        df=pd.read_sql(
            query,
            conn,
            params=(date,fund_id)
        )


        if df.empty:
            return None


        row=df.iloc[0].to_dict()


        if row.get("breakdown_json"):

            row["breakdown"]=json.loads(
                row["breakdown_json"]
            )


        return row


    finally:

        if close_conn:
            conn.close()



def get_top_performers(top_n=10):

    return get_general_ranking(top_n)



def get_top_category_leaders():

    conn=get_db_connection()

    try:

        date=get_latest_score_date(conn)


        query="""

        SELECT *

        FROM fund_scores

        WHERE date=?
        AND category_rank=1

        ORDER BY final_score DESC

        """


        return pd.read_sql(
            query,
            conn,
            params=(date,)
        )


    finally:

        conn.close()