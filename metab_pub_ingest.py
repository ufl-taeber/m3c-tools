"""M3C PubMed publication importer.

Usage:
    python3 metab_pub_ingest.py -h | --help
    python3 metab_pub_ingest.py <config> all
    python3 metab_pub_ingest.py <config> [only | except] <person_id>...

Options:
    -h --help    Show this message and exit.

Example: Import everyone's publications
    $ python metab_pub_ingest.py config.yaml all

Example: Import James's publications (person_id=007)
    $ python metab_pub_ingest.py config.yaml only 007

Example: Import everyone except James and Alec's publications
    $ python metab_pub_ingest.py config.yaml except 006 007

Copyright 2019–2020 University of Florida.
"""

import datetime
import os
import sys
import traceback
import typing
import yaml

import psycopg2

from aide import Aide
from metab_classes import Person
from metab_classes import Publication
from metab_classes import DateTimeValue


class Citation(object):
    def __init__(self, data):
        self.data = data

    def check_key(self, paths, data=None):
        if not data:
            data = self.data
        if paths[0] in data:
            trail = data[paths[0]]
            if len(paths) > 1:
                trail = self.check_key(paths[1:], trail)
            return trail
        else:
            return ''


def get_config(config_path: str) -> dict:
    try:
        with open(config_path, 'r') as config_file:
            config = yaml.load(config_file.read(), Loader=yaml.FullLoader)
    except Exception as e:
        print("Error: Check config file")
        sys.exit(e)
    return config


def connect(host: str, db: str, user: str, pg_password: str, port: str) \
                    -> psycopg2.extensions.cursor:
    conn = psycopg2.connect(host=host, dbname=db, user=user,
                            password=pg_password, port=port)
    cur = conn.cursor()
    return cur


def get_people(cur: psycopg2.extensions.cursor, person_id: str = None) -> dict:
    people = {}
    if person_id:
        cur.execute("""\
                SELECT id, first_name, last_name
                FROM people
                JOIN names
                ON id=person_id
                WHERE id=%s""", (int(person_id),))
    else:
        cur.execute("""\
                SELECT id, first_name, last_name
                FROM people
                JOIN names
                ON id=person_id""")
    for row in cur:
        person = Person(person_id=row[0], first_name=row[1], last_name=row[2])
        people[person.person_id] = person
    return people


def get_affiliations(cur: psycopg2.extensions.cursor, person_id: str) -> typing.List[str]:
    cur.execute("""\
        SELECT o.name
        FROM organizations o, people p, associations a
        WHERE
        o.id = a.organization_id AND
        a.person_id = p.id AND
        p.id = %s AND
        o.withheld = FALSE AND
        o.type = 'institute'""", (int(person_id),))
    return [row[0] for row in cur]


def get_supplementals(cur: psycopg2.extensions.cursor, person_id: str = None)\
        -> (dict, dict):
    extras = {}
    exceptions = {}
    if person_id:
        cur.execute("""\
            SELECT pmid, person_id, include
            FROM publications
            WHERE person_id=%s""", (person_id,))
    else:
        cur.execute("""\
            SELECT pmid, person_id, include
            FROM publications""")
    for row in cur:
        pmid = row[0]
        person_id = int(row[1])
        include = row[2]
        if include:
            if person_id in extras.keys():
                extras[person_id].append(pmid)
            else:
                extras[person_id] = [pmid]
        else:
            if person_id in exceptions.keys():
                exceptions[person_id].append(pmid)
            else:
                exceptions[person_id] = [pmid]

    return extras, exceptions


def get_ids(aide: Aide, person: Person, affiliations: typing.List[str]) -> list:
    ''' Get the PMIDs associated with a person with the passed affilitions.
        Returns an empty array if no affiliations are passed.

        Here is an example of a full query with a person with first name Arthur, last name Edison, and two affiliations

        Edison Arthur[Author - Full] AND (University of Florida[Affiliation] OR University of Georgia[Affiliation])

        Which PubMed turns into:

        Edison, Arthur[Full Author Name] AND (University of Florida[Affiliation] OR University of Georgia[Affiliation])
    '''
    query = person.first_name + ' ' + person.last_name + '[Author - Full]'
    if len(affiliations) > 0:
        query += ' AND ('
        for affiliation in affiliations:
            query += f'{affiliation}[Affiliation] OR '
        # Trim off the trailing OR
        query = query[:-4]
        query += ')'
    else:
        print(f'Missing Affiliation for person_id: {person.person_id}. Skipping...')
        return []
    id_list = aide.get_id_list(query)
    return id_list


def parse_api(results: dict) -> typing.Dict[str, Publication]:
    publications: typing.Dict[str, Publication] = {}

    for article in results['PubmedArticle']:
        try:
            citation = Citation(article)
            pub = make_pub(citation)
            if not pub.pmid or not pub.published:
                continue
            publications[pub.pmid] = pub
        except Exception:
            citation = Citation(article)
            pmid = str(citation.check_key(['MedlineCitation', 'PMID']))
            print(f'Skipping publication {pmid}')
            continue

    return publications


MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def make_pub(citation: Citation) -> Publication:
    title = (citation.check_key(
        ['MedlineCitation', 'Article', 'ArticleTitle'])).replace('"', '\\"')

    # For more information on parsing publication dates in PubMed, see:
    #   https://www.nlm.nih.gov/bsd/licensee/elements_descriptions.html#pubdate
    published = None
    pubdate = citation.check_key(
        ['MedlineCitation', 'Article', 'Journal', 'JournalIssue', 'PubDate'])
    if pubdate:
        if 'MedlineDate' in pubdate:
            year = int(pubdate['MedlineDate'][0:4])
            assert 1900 < year and year < 3000
        else:
            year = int(pubdate['Year'])

        try:
            month_text = pubdate['Month']
            month = MONTHS.index(month_text)+1
        except (KeyError, ValueError):
            month = None

        try:
            day = int(pubdate['Day'])
        except KeyError:
            day = None

        published = DateTimeValue(year, month, day)

    pmid = str(citation.check_key(['MedlineCitation', 'PMID']))
    try:
        count = 0
        proto_doi = citation.check_key(['PubmedData', 'ArticleIdList'])[count]
        while proto_doi.attributes['IdType'] != 'doi':
            count += 1
            proto_doi = citation.check_key(['PubmedData',
                                            'ArticleIdList'])[count]
        doi = str(proto_doi)
    except IndexError:
        doi = ''

    # create citation
    author_list = citation.check_key(['MedlineCitation', 'Article',
                                      'AuthorList'])
    names = []
    for author in author_list:
        if 'CollectiveName' in author:
            names.append(author['CollectiveName'])
            continue
        last_name = author['LastName']
        initial = author['Initials']
        name = last_name + ", " + initial + "."
        names.append(name)
    volume = citation.check_key(['MedlineCitation', 'Article', 'Journal',
                                 'JournalIssue', 'Volume'])
    issue = citation.check_key(['MedlineCitation', 'Article', 'Journal',
                                'JournalIssue', 'Issue'])
    pages = citation.check_key(['MedlineCitation', 'Article', 'Pagination',
                                'MedlinePgn'])
    journal = citation.check_key(['MedlineCitation', 'Article', 'Journal',
                                  'Title']).title()

    cite = ', '.join(names)
    if published:
        cite += f' ({published.year}). '
    cite += title
    if not cite.endswith('.'):
        cite += '. '
    else:
        cite += ' '
    if journal:
        cite += journal
        if volume or issue:
            cite += ', '
            if volume:
                cite += volume
            if issue:
                cite += '(' + issue + ')'
        if pages:
            cite += ', ' + pages
        cite += '. '
    if doi:
        cite += 'doi:' + doi
    citation = cite

    return Publication(pmid, title, published, doi, citation)


def write_triples(aide: Aide, person: Person, pubs: dict) -> list:
    rdf = []
    for pub in pubs.values():
        rdf.extend(pub.add_person(aide.namespace, person.person_id))
    return rdf


def print_to_file(triples: list, file: str) -> None:
    triples = [t + " ." for t in triples]
    with open(file, 'a+') as rdf:
        rdf.write("\n".join(triples))
        rdf.write("\n")
    return


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ["-h", "--help"]:
        print(__doc__)
        sys.exit()

    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    config_path = sys.argv[1]
    cmd = sys.argv[2]
    person_ids: typing.List[str] = sys.argv[3:]

    if cmd not in ["all", "only", "except"]:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)

    timestamp = datetime.datetime.now()
    # Path will look like: data_out/2012/06/2012_06_23
    path = os.path.join("data_out",
                        timestamp.strftime("%Y"),
                        timestamp.strftime("%m"),
                        timestamp.strftime("%Y_%m_%d"))
    os.makedirs(path, exist_ok=True)

    config = get_config(config_path)

    aide = Aide(config.get('update_endpoint'),
                config.get('vivo_email'),
                config.get('vivo_password'),
                config.get('namespace'),
                config.get('pubmed_email'),
                config.get('pubmed_api_token'))

    cur = connect(config.get('sup_host'), config.get('sup_database'),
                  config.get('sup_username'), config.get('sup_password'),
                  config.get('sup_port'))

    people: typing.Dict[str, Person] = get_people(cur, None)

    if cmd == "all":
        person_ids = list(map(str, people.keys()))
    elif cmd == "only":
        pass  # Use person_ids as is
    elif cmd == "except":
        remaining: typing.List[str] = []
        for pid in people.keys():
            person_id = str(pid)
            if person_id not in person_ids:
                remaining.append(person_id)
        person_ids = remaining

    pmid_to_person = {}
    for person_id in person_ids:
        try:
            extras, exceptions = get_supplementals(cur, person_id)
            person = people[int(person_id)]

            pmids = get_ids(aide, person, get_affiliations(cur, person_id))
            if person.person_id in extras.keys():
                for pub in extras[person.person_id]:
                    if pub not in pmids:
                        pmids.append(pub)
            if person.person_id in exceptions.keys():
                for pub in exceptions[person.person_id]:
                    if pub in pmids:
                        pmids.remove(pub)
            if pmids:
                for pmid in pmids:
                    if pmid_to_person.get(pmid):
                        pmid_to_person[pmid].append(person_id)
                    else:
                        pmid_to_person[pmid] = [person_id]
        except Exception:
            print(f"Error while processing {person_id}", file=sys.stderr)
            traceback.print_exc()
            continue

    BATCH_SIZE = 5000
    # Make the dict into a list so that it is ordered and we can batch process it
    # Turns into a list of 2-tuples (pmids, person)
    pmid_to_person_list = list(pmid_to_person.items())
    curr_items = []
    batch = 0
    while len(pmid_to_person_list) != 0:
        batch += 1
        curr_items = pmid_to_person_list[:BATCH_SIZE]
        pmid_to_person_list = pmid_to_person_list[BATCH_SIZE:]
        try:
            triples = []
            pub_collective = {}

            results = aide.get_details([item[0] for item in curr_items])
            pubs = parse_api(results)
            pub_collective.update(pubs)
            for pub in pubs.values():
                for person_id in pmid_to_person[pub.pmid]:
                    person = people[int(person_id)]
                    print_to_file(write_triples(aide, person, {pub.pmid: pub}), os.path.join(path, f'{person.person_id}_pubs.nt'))
                triples.extend(pub.get_triples(aide.namespace))

            pub_file = os.path.join(path, f"pub_info.nt")
            print_to_file(triples, pub_file)

            print(f'Batch {batch} with {len(pmid_to_person_list)} pubs to go')
        except Exception:
            print(f"Error while processing PMIDs", file=sys.stderr)
            traceback.print_exc()
            continue


if __name__ == "__main__":
    main()
