"""
Metab Importer
Usage:
    import.py (-h | --help)
    import.py <path_to_config>

Options:
    -h --help       Show this message and exit

Instructions:
    Run the importer where you have access to the postgres metabolomics
    database.
"""

from datetime import datetime
import os
import sys
import yaml

import psycopg2

from aide import Aide
from metab_classes import Dataset
from metab_classes import Organization
from metab_classes import Person
from metab_classes import Project
from metab_classes import Study


def get_config(config_path):
    try:
        with open(config_path, 'r') as config_file:
            config = yaml.load(config_file.read(), Loader=yaml.FullLoader)
    except Exception as e:
        print("Error: Check config file")
        sys.exit(e)
    return config


def connect(host, db, user, pg_password, port):
    conn = psycopg2.connect(host=host, dbname=db, user=user,
                            password=pg_password, port=port)
    cur = conn.cursor()
    return cur


def get_organizations(sup_cur):
    print("Gathering Organizations")
    orgs = {}
    org_names = []
    sup_cur.execute("""\
                    SELECT id, name, type
                    FROM organizations""")
    for row in sup_cur:
        org = Organization()
        org.org_id = row[0]
        org.name = row[1]
        org.type = row[2]
        orgs[org.org_id] = org
        org_names.append(org.name)
    return orgs, org_names


def make_organizations(namespace, orgs):
    print("Making Organizations")
    triples = []
    org_count = 0
    for org in orgs.values():
        org.uri = namespace + str(org.org_id)
        triples.extend(org.get_triples())
        org_count += 1
    print("There are " + str(org_count) + " organizations.")
    return triples


def get_people(sup_cur):
    print("Gathering People")
    people = {}
    sup_cur.execute("""\
            SELECT id, first_name, last_name, display_name, email, phone
            FROM people
            JOIN names
            ON id=person_id""")
    for row in sup_cur:
        person = Person()
        person.person_id = row[0]
        person.first_name = row[1]
        person.last_name = row[2]
        person.display_name = row[3]
        person.email = row[4]
        person.phone = row[5]
        people[person.person_id] = person
    return people


def make_people(namespace, people):
    print("Making People Profiles")
    triples = []
    people_count = 0
    for person in people.values():
        person.uri = namespace + str(person.person_id)
        if not person.display_name:
            person.make_display_name()
        triples.extend(person.get_triples())
        people_count += 1
    print("There are " + str(people_count) + " people.")
    return triples


def link_people_to_org(sup_cur, people, orgs):
    triples = []
    for person in people.values():
        sup_cur.execute("""\
                    SELECT person_id, organization_id
                    FROM associations
                    WHERE person_id=%s""", (person.person_id,))
        for row in sup_cur:
            triples.extend(orgs[row[1]].add_person(person.uri))
    return triples


def get_projects(mwb_cur, sup_cur, people, org_names):
    print("Gathering Workbench Projects")
    projects = {}
    mwb_cur.execute("""\
        SELECT project_id, project_title, project_type, project_summary,
               doi, funding_source, last_name, first_name, institute,
               department, laboratory
          FROM project
    """)
    for row in mwb_cur:
        project = Project()
        project.project_id = row[0].replace('\n', '')
        project.project_title = row[1].replace('\n', '')
        if row[2]:
            project.project_type = row[2].replace('\n', '')
        if row[3]:
            project.summary = row[3].replace('\n', '').replace('"', '\\"')
        if row[4]:
            project.doi = row[4].replace('\n', '')
        if row[5]:
            project.funding_source = row[5].replace('\n', '')
        last_name = row[6]
        first_name = row[7]
        # if project.project_id == "PR000048":
        #     import pdb
        #     pdb.set_trace()
        if row[8]:
            if row[8].lower() != 'none':
                institute = row[8]
            else:
                institute = None
        else:
            institute = None
        if row[9]:
            if row[9].lower() != 'none':
                department = row[9]
            else:
                department = None
        else:
            department = None
        if row[10]:
            if row[10].lower() != 'none':
                lab = row[10]
            else:
                institute = None
        else:
            lab = None
        missing_orgs = list({institute, department, lab} - set(org_names) -
                        {None,})
        if missing_orgs:
            print("Error: While processing project " + project.project_id +
                 ", the following missing organizations were found")
            print(missing_orgs)
            sys.exit()
        sup_cur.execute("""\
                    SELECT person_id
                    FROM names
                    WHERE last_name=%s AND first_name=%s""",
                    (last_name, first_name))
        try:
            person_id = sup_cur.fetchone()[0]
            project.pi_uri = people[person_id].uri
        except KeyError:
            print("Error: Person does not exist.")
            print("PI for project " + project.project_id)
            print("Last name: " + project.last_name)
            print("First name: " + project.first_name)
            sys.exit()
        projects[project.project_id] = project
    return projects


def make_projects(namespace, projects):
    print("Making Workbench Projects")
    triples = []
    project_count = 0
    for project in projects.values():
        project.uri = namespace + project.project_id
        triples.extend(project.get_triples())
        triples.extend(project.add_person())
        project_count += 1
    print("There are " + str(project_count) + " projects.")
    return triples


def get_studies(mwb_cur, sup_cur, people, org_names):
    print("Gathering Workbench Studies")
    studies = {}
    mwb_cur.execute("""\
        SELECT study_id, study_title, study_type, study_summary,
            project_id, last_name, first_name, institute, department,
            laboratory
        FROM study""")
    for row in mwb_cur:
        study = Study()
        study.study_id = row[0].replace('\n', '')
        study.study_title = row[1].replace('\n', '')
        if row[2]:
            study.study_type = row[2].replace('\n', '')
        if row[3]:
            study.summary = row[3].replace('\n', '').replace('"', '\\"')
        study.project_id = row[4].replace('\n', '')
        last_name = row[6]
        first_name = row[7]
        if row[8]:
            if row[8].lower() != 'none':
                institute = row[8]
            else:
                institute = None
        else:
            institute = None
        if row[9]:
            if row[9].lower() != 'none':
                department = row[9]
            else:
                department = None
        else:
            department = None
        if row[10]:
            if row[10].lower() != 'none':
                lab = row[10]
            else:
                institute = None
        else:
            lab = None
        missing_orgs = list({institute, department, lab} - set(org_names) - 
                        {None,})
        if missing_orgs:
            print("Error: The following organizations are missing")
            print(missing_orgs)
            sys.exit()
        sup_cur.execute("""\
                    SELECT person_id
                    FROM names
                    WHERE last_name=%s AND first_name=%s""",
                    (last_name, first_name))
        try:
            person_id = sup_cur.fetchone()[0]
            study.pi_uri = people[person_id].uri
        except IndexError:
            print("Error: Person does not exist.")
            print("Runner for study " + study.study_id)
            print("Last name: " + study.last_name)
            print("First name: " + study.first_name)
            sys.exit()
        studies[study.study_id] = study
    return studies


def make_studies(namespace, studies, projects):
    print("Making Workbench Studies")
    triples = []
    study_count = 0
    no_proj_study = 0
    for study in studies.values():
        study.uri = namespace + study.study_id
        if study.project_id in projects.keys():
            project_uri = projects[study.project_id].uri
        else:
            project_uri = None
            no_proj_study += 1
        triples.extend(study.get_triples(project_uri))
        study_count += 1
    print("There are " + str(study_count) + " studies.")
    if no_proj_study > 0:
        print("There are " + str(no_proj_study) + " studies without projects")
    return triples


def get_datasets(mwb_cur):
    print("Gathering Workbench Datasets")
    datasets = {}
    mwb_cur.execute("""\
        SELECT mb_sample_id, study_id, subject_species
        FROM metadata
        INNER JOIN subject
        ON metadata.subject_id = subject.subject_id""")
    for row in cur:
        dataset = Dataset()
        dataset.mb_sample_id = row[0]
        dataset.study_id = row[1]
        if row[2]:
            dataset.subject_species = row[2].replace('\n', '')
        datasets[dataset.mb_sample_id] = dataset
    return datasets


def make_datasets(namespace, datasets, studies):
    print("Making Workbench Datasets")
    triples = []
    dataset_count = 0
    no_study_datasets = 0
    for dataset in datasets.values():
        dataset.uri = namespace + dataset.mb_sample_id
        if dataset.study_id in studies.keys():
            study_uri = studies[dataset.study_id].uri
        else:
            study_uri = None
            no_study_datasets += 1
        triples.extend(dataset.get_triples(study_uri))
        dataset_count += 1
    print("There will be " + str(dataset_count) + " new datasets.")
    if no_study_datasets > 0:
        print("There are {} datasets without studies"
              .format(no_study_datasets))
    return triples


def print_to_file(triples, file):
    with open(file, 'a+') as rdf:
        rdf.write(" . \n".join(triples))
        rdf.write(" . \n")


def do_upload(aide, triples):
    chunks = [triples[x:x+15] for x in range(0, len(triples), 15)]
    for chunk in chunks:
        query = """
            INSERT DATA {{
                GRAPH <http://vitro.mannlib.cornell.edu/default/vitro-kb-2> {{
                        {}
                    }}
            }}
        """.format(" . \n".join(chunk))
        aide.do_update(query)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    if sys.argv[1] in ["-h", "--help"]:
        print(__doc__)
        sys.exit()

    config_path = sys.argv[1]

    timestamp = datetime.now()
    path = 'data_out/' + timestamp.strftime("%Y") + '/' + \
        timestamp.strftime("%m") + '/' + timestamp.strftime("%Y_%m_%d")
    try:
        os.makedirs(path)
    except FileExistsError:
        pass
    org_file = os.path.join(path, 'orgs.rdf')
    people_file = os.path.join(path, 'people.rdf')
    project_file = os.path.join(path, 'projects.rdf')
    study_file = os.path.join(path, 'studies.rdf')
    dataset_file = os.path.join(path, 'datasets.rdf')

    config = get_config(config_path)
    aide = Aide(config.get('update'),
                config.get('vivo_email'),
                config.get('vivo_password'),
                config.get('namespace'))
    mwb_cur = connect(config.get('mwb_host'), config.get('mwb_database'),
                      config.get('mwb_username'), config.get('mwb_password'),
                      config.get('mwb_port'))
    sup_cur = connect(config.get('sup_host'), config.get('sup_database'),
                      config.get('sup_username'), config.get('sup_password'),
                      config.get('sup_port'))

    # Organizations
    orgs, org_names = get_organizations(sup_cur)
    org_triples = make_organizations(aide.namespace, orgs)
    print_to_file(org_triples, org_file)

    # People
    people = get_people(sup_cur)
    people_triples = make_people(aide.namespace, people)
    people_triples.extend(link_people_to_org(sup_cur, people, orgs))
    print_to_file(people_triples, people_file)

    # Projects
    projects = get_projects(mwb_cur, sup_cur, people, org_names)
    project_triples = make_projects(aide.namespace, projects)
    print_to_file(project_triples, project_file)

    # Studies
    studies = get_studies(mwb_cur, sup_cur, people, org_names)
    study_triples = make_studies(aide.namespace, studies, projects)
    print_to_file(study_triples, study_file)

    # Datasets
    datasets = get_datasets(mwb_cur)
    dataset_triples = make_datasets(aide.namespace, datasets, studies)
    print_to_file(dataset_triples, dataset_file)

    # If you've made it this far, it's time to delete
    # aide.do_delete()
    # do_upload(aide, org_triples)
    # do_upload(aide, people_triples)
    # do_upload(aide, project_triples)
    # do_upload(aide, study_triples)
    # do_upload(aide, dataset_triples)


if __name__ == "__main__":
    main()
