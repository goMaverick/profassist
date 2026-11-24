"""Seed content for the MAAI 903 subject outline. The professor can edit every field."""

POLICIES = [
    {
        "key": "academic_integrity",
        "title": "Academic integrity",
        "body": (
            "Plagiarism and cheating are serious offences. Students submit written work through "
            "the integrity system named in the first lecture. A flag in ProfAssist is evidence for "
            "a conversation, not a verdict."
        ),
    },
    {
        "key": "attendance",
        "title": "Attendance",
        "body": (
            "Students attend the scheduled lecture and workshop. Missing the attendance rule in "
            "the faculty policy can lead to a fail even when the composite mark is a pass."
        ),
    },
    {
        "key": "lecture_capture",
        "title": "Lecture capture",
        "body": (
            "Lectures may be recorded for students enrolled in the subject. Recordings stay on the "
            "university platform and are not a substitute for the workshop."
        ),
    },
    {
        "key": "sustainability",
        "title": "Sustainability",
        "body": (
            "Workshop briefs are published on the learning site. Printed copies are not handed out "
            "in class. Submit electronic copies."
        ),
    },
]

BASICS_FIELDS = (
    "name",
    "code",
    "section",
    "credit_points",
    "year",
    "session",
    "duration",
    "prerequisites",
    "equivalent_subjects",
    "delivery_mode",
)

LECTURE_FIELDS = (
    "day",
    "time",
    "location",
    "educator_name",
    "office",
    "email",
    "consultation",
)

POLICY_DOCUMENTS = [
    "Academic Grievance Policy",
    "Academic Integrity Policy",
    "Campus Access and Order Rules",
    "Code of Conduct \u2013 Library Users",
    "Code of Practice \u2013 Students",
    "Copyright Policy",
    "Intellectual Property Policy",
    "Library Regulations",
    "Minimum Rate of Progress",
    "Music, Video and Software Piracy",
    "Non-Discriminatory Language and Practice & Presentation Policy and Guidelines",
    "Special Consideration Policy & Procedure",
    "Student Attendance Policy",
    "Student Conduct Rules",
    "Rules for use of UOWD ITTS Facilities",
    "Teaching and Assessment: Code of Practice \u2013 Teaching",
    "Teaching and Assessment: Assessment and Feedback Policy",
    "Teaching and Assessment: Subject Delivery Policy",
]

GENAI_INTRO = (
    "GenAI technology (such as ChatGPT or Microsoft Co-pilot) is reshaping the University "
    "experience worldwide. UOW is committed to embracing GenAI as a tool to enhance learning "
    "experiences and develop vital work-readiness skills. However, misuse or use of GenAI in "
    "assessments where prohibited constitutes academic misconduct (as specified by University "
    "Policy). It is important that students check if GenAI is permitted for each assessment task "
    "and how it is to be used and acknowledged. Please read the student guidance (Acknowledging "
    "the permitted use of GenAI in assessments, Using Generative AI tools well and Access your "
    "UOW Microsoft Copilot account) available on how to use GenAI ethically and critically, "
    "equally recognising its capabilities and limitations. For example:"
)

GENAI_POINTS = [
    (
        "Generative AI is not a substitute for decision-making: GenAI should complement, not "
        "replace, your critical thinking and decision-making skills."
    ),
    (
        "Output quality depends on prompts: The quality of GenAI outputs is influenced by "
        "prompting. Poorly constructed or unclear prompts may generate outputs that are incorrect."
    ),
    (
        "Fact verification is essential: GenAI outputs can be fabricated, presenting inaccurate "
        "information or contain harmful bias. Verify all GenAI outputs against reliable sources."
    ),
    (
        "Protect data and copyright: Many GenAI technologies collect information in ways that "
        "breach privacy and data protection provisions, particularly where the source material is "
        "confidential or subject to copyright. Please check the Terms and Conditions of GenAI "
        "technologies and if unsure, contact UOW Copyright Guidance. Learn more about how to "
        "access UOW secured GenAI tools here."
    ),
    (
        "Transparency in use: Where required, you must acknowledge GenAI use, including providing "
        "prompt histories and detailing how GenAI was utilised."
    ),
    (
        "Thoughtful and appropriate application: Be mindful of when and how to use GenAI tools. "
        "Assess its appropriateness for each use, and refrain from use when not suitable."
    ),
]

GRADES = [
    {"band": "High Distinction (HD)", "range": "85 \u2013 100%", "description": ""},
    {"band": "Distinction (D)", "range": "75 \u2013 84%", "description": ""},
    {"band": "Credit (C)", "range": "65 \u2013 74%", "description": ""},
    {"band": "Pass (P)", "range": "50 \u2013 64%", "description": ""},
    {"band": "Pass Supplementary (PS)", "range": "50%", "description": ""},
    {
        "band": "Fail (F)",
        "range": "0 \u2013 49%",
        "description": "And not meeting the attendance requirements.",
    },
    {
        "band": "Technical Fail (TF)",
        "range": "Not meeting the final exam passing requirements",
        "description": "See the Assessment Policy PP-REG-DB-2.1.",
    },
]

SATISFACTORY = [
    (
        "In order to be considered for a grade of Pass (P) or better in this subject, students must "
        "achieve the minimum required mark in the Final Examination (see page 1 for required score); "
        "students who obtain a composite mark greater than or equal to 50% but do not satisfy the "
        "Final Examination minimum pass requirements in the final examination will be awarded a "
        "\u201cTechnical Fail\u201d grade."
    ),
    (
        "Students must \u2018reasonably\u2019 complete all assessment tasks (including the required "
        "score for the Final Examination,) and submit these as specified in the subject outline. "
        "\u2018Reasonable\u2019 completion of an assessment task will be determined based on the "
        "instructions given to the student including: word length, demonstration of research and "
        "analysis where required, adherence to the Plagiarism Policy guidelines, and completion of "
        "each section/component of the assessment. Failure to submit all assessment tasks may result "
        "in a Fail grade awarded for the subject."
    ),
]

SATISFACTORY_NOTE = (
    "Template note: this section refers to a Final Examination minimum on page 1, but this "
    "subject's page 1 defines no final examination. Confirm the requirement with the faculty "
    "before publishing."
)

ACADEMIC_INTEGRITY = {
    "intro": (
        "Plagiarism and cheating are serious offences that can lead to expulsion from the "
        "university. Students must be familiar with the Academic Integrity policy which outlines "
        "the procedure that will be followed in case of academic misconduct including cheating and "
        "plagiarism. Please refer to How to Avoid Plagiarism available on the Student Online "
        "Resources website (http://my.uowdubai.ac.ae)."
    ),
    "turnitin": (
        "Students are required to submit all written assignments in soft copy through the TurnItIn "
        "system which is available online at www.turnitin.com. Every student must have a TurnItIn "
        "account. Failure to submit an assignment through TurnItIn will result in marks for that "
        "assignment being withheld. Students do NOT need to hand in a printed copy of the TurnItIn "
        "Originality Report. More information about TurnItIn (including how to create an account "
        "and add a class) will be provided in the first lecture. Students can download Frequently "
        "Asked Questions (FAQs) about TurnItIn from the SSP section of UOWD website "
        "(https://www.uowdubai.ac.ae/academic-resources/student-support-programs)."
    ),
    "turnitin_fields": [
        {"label": "Class ID", "value": "Moodle Link"},
        {"label": "Password", "value": "Moodle Link"},
    ],
    "referencing": (
        "For information about referencing and in-text citation please review the Academic Writing "
        "Presentation available on the Student Online Resources website "
        "(http://my.uowdubai.ac.ae)."
    ),
    "rules": (
        "For information about UOWD Rules and Policies, please go to the Student Online Resources "
        "website (http://my.uowdubai.ac.ae) and click on the POLICIES link."
    ),
}

ATTENDANCE = (
    "Attendance in this subject is compulsory. Failure to attend all tutorials and computer "
    "workshops as per the Student Attendance Policy may result in a FAIL grade. Students are "
    "strongly encouraged to become familiar with this policy (which can be found on the Online "
    "Resources website at my.uowdubai.ac.ae)."
)

SUPPLEMENTARY = (
    "A supplementary assessment may be offered to students whose performance in this subject is "
    "close (45-49 in the final examination and 48-49 in the composite score) to that required to "
    "pass the subject, and are otherwise identified as meriting an offer of a supplementary "
    "assessment. The precise form of a supplementary assessment will be determined at the time the "
    "offer of a supplementary is made."
)

LECTURE_CAPTURE = (
    "UOWD supports the recording of lectures as a supplemental study tool, to provide students "
    "with equity of access, and as a technology-enriched learning strategy to enhance the student "
    "experience. To make your own recording of a lecture you must receive the explicit permission "
    "of the Educator and those people who are also being recorded. You may only use recorded "
    "lectures, whether they are your own or recorded by the university, for your own educational "
    "purposes. Recordings cannot be altered, shared or published on another platform, without "
    "permission of the University. UOWD\u2019s Lecture Capture policy is underdevelopment."
)

SUSTAINABILITY = (
    "UOWD encourages all students to act in a sustainable manner when planning and submitting "
    "assessments. If possible, students should not use plastic items, such as folders, covers, and "
    "bindings, and other synthetic materials, for presentations, workshops, and other activities. "
    "Students are also encouraged to avoid unnecessary printing; and if printing is required, "
    "please consider printing double-sided and only printing essential illustrations avoiding "
    "blocks of any colour as the use of ink is harmful to the environment. Always behave in a "
    "sustainable way."
)

SSP = (
    "SSP (Student Support Program) is a program committed to assisting students in developing "
    "their academic skills and getting the most out of their studies. As part of their services, "
    "SSP provides Peer Tutoring Program and Academic Workshops "
    "(https://my.uowdubai.ac.ae/ssd/index.php). Studiosity is an online study tool that students "
    "can access 24 hours, 7 days a week! Students can receive feedback on submitted writing in "
    "less than 24 hours and receive one-to-one, personal help in real time with a subject "
    "specialist. The service can be accessed through the subject\u2019s Moodle site. For further "
    "information, please contact: SSP Coordinator, Room 020, Block 5, ssp@uowdubai.ac.ae, Phone "
    "Number: +971 4 278 1756."
)

LATE_SUBMISSION = (
    "Please note that late submissions will incur a penalty of 20% per day, including weekends."
)

SUPPORTING_INTRO = (
    "Books, Articles, Videos, Podcasts, etc. will be available on our Learning Management System "
    "(LMS)."
)

SUPPORTING_ACCESS = (
    "The University uses MOODLE as a Learning Management System (LMS) to support all coursework "
    "subjects. The subject site and supporting materials can be accessed via: "
    "https://moodle.uowplatform.edu.au And via UOWD Library"
)

POLICY_INTRO = (
    "All students must read and be familiar with the following UOWD policies and documents, which "
    "are available on the Student Online Resources (my.uowdubai.ac.ae) website by following the "
    "Policies link:"
)


def _levels(beginning: str, developing: str, proficient: str, advanced: str) -> dict[str, str]:
    return {
        "beginning": beginning,
        "developing": developing,
        "proficient": proficient,
        "advanced": advanced,
    }


def _rubric(name: str, weight: int, levels: dict[str, str]) -> dict:
    return {"name": name, "weight": weight, "levels": levels}


def _assessment_tasks() -> list[dict]:
    return [
        {
            "number": "A1",
            "title": "Workshops",
            "type": "Individual",
            "weight": 25,
            "total_marks": 100,
            "due": "Throughout the semester",
            "lo_codes": ["LO2", "LO3", "LO4"],
            "overview": [
                "Specifications of all practical activities will be released in workshop. There "
                "will be NO printed hardcopies distributed during lecture or workshop classes. The "
                "students will collect the electronic copies of specifications on "
                "cs.uowdubai.ac.ae web site for the course."
            ],
            "deliverables": [],
            "format": [],
            "rubric": [
                _rubric("Quality of solution", 20, _levels("", "", "", "")),
                _rubric("Accuracy of implementation", 30, _levels("", "", "", "")),
                _rubric(
                    "Quality of results which will be tested by the lecturer",
                    30,
                    _levels("", "", "", ""),
                ),
                _rubric("Clarity of solution documentation", 20, _levels("", "", "", "")),
            ],
        },
        {
            "number": "A2",
            "title": "Solution Architecture Report",
            "type": "Individual",
            "weight": 25,
            "total_marks": 100,
            "due": "Week 7",
            "lo_codes": ["LO1", "LO3", "LO5"],
            "overview": [
                "This assessment requires students to design an AI solution architecture for a "
                "realistic business or industry problem. Students must document and justify their "
                "approach to data flow, model selection, orchestration of pipelines, deployment "
                "strategies, monitoring mechanisms, and tool choices. The proposed solution must "
                "reflect real-world constraints and considerations (e.g., scalability, "
                "reproducibility, latency, compliance). Students may choose a problem from a "
                "provided list or propose their own, subject to the lecturer's approval.",
                "A structured technical report (max 2,500 words) including visualizations (e.g., "
                "timelines, screenshots, tables) covering:",
            ],
            "deliverables": [
                "Executive Summary",
                "Problem Definition & Business Context",
                "Solution Overview",
                "Data Strategy",
                "AI Workflow Design (ML Pipeline)",
                "Tool & Technology Stack",
                "Model Deployment & Scalability Strategy",
                "Monitoring, Retraining & Maintenance",
                "Ethical, Regulatory, and Risk Considerations",
                "Conclusion & Recommendations",
                "References",
            ],
            "format": [],
            "rubric": [
                _rubric(
                    "Problem Definition & Business Context",
                    15,
                    _levels(
                        "Problem is vague, missing, or irrelevant to the brief.",
                        "Problem is defined but lacks clarity or context.",
                        "Problem is defined with some context and relevance to business goals.",
                        "Problem is clearly articulated, well contextualized in the industry, and "
                        "tied to measurable business impact.",
                    ),
                ),
                _rubric(
                    "Solution Design & Architecture",
                    25,
                    _levels(
                        "Incomplete, generic, or technically flawed solution. No meaningful "
                        "architecture provided.",
                        "Basic solution proposed with limited justification; architecture lacks "
                        "clarity.",
                        "Solution is technically reasonable with minor gaps; architecture is mostly "
                        "clear.",
                        "Solution is innovative, technically sound, and clearly aligned with the "
                        "business problem. Includes a well-labelled architecture diagram.",
                    ),
                ),
                _rubric(
                    "Data Strategy & Pipeline Design",
                    20,
                    _levels(
                        "Minimal or incorrect pipeline and data handling strategy.",
                        "Pipeline and data strategy are basic and partially developed.",
                        "Sound approach to data and pipeline design, with some detail provided.",
                        "Comprehensive explanation of data sourcing, preparation, storage, and "
                        "pipeline logic; pipeline design is robust and well-integrated.",
                    ),
                ),
                _rubric(
                    "Deployment & MLOps Planning",
                    15,
                    _levels(
                        "No clear deployment plan or inappropriate MLOps choices.",
                        "Basic deployment approach described; MLOps tools not well integrated.",
                        "Good deployment plan with some CI/CD and monitoring considerations.",
                        "Clear and feasible deployment strategy including CI/CD, scalability, "
                        "monitoring, and maintenance. MLOps tools well selected.",
                    ),
                ),
                _rubric(
                    "Ethical, Regulatory, and Risk Considerations",
                    15,
                    _levels(
                        "Lacks awareness or discussion of ethical or legal issues.",
                        "Some ethical and regulatory factors mentioned with limited analysis.",
                        "Covers key ethical and legal aspects with moderate depth.",
                        "Demonstrates critical awareness of ethical AI, fairness, explainability, "
                        "privacy, and legal frameworks.",
                    ),
                ),
                _rubric(
                    "Presentation, Clarity, and Referencing",
                    10,
                    _levels(
                        "Poorly written or disorganized; citations missing or incorrect.",
                        "Adequate clarity but disorganized in places; referencing incomplete.",
                        "Generally well-written and structured; minor language or citation issues.",
                        "Professionally presented, well-structured, clear language, and all sources "
                        "are correctly cited.",
                    ),
                ),
            ],
        },
        {
            "number": "A3",
            "title": "Group Project: Deployable AI System",
            "type": "Group",
            "weight": 40,
            "total_marks": 100,
            "due": "Week 11",
            "lo_codes": ["LO1", "LO2", "LO3", "LO4", "LO6"],
            "overview": [
                "In this assessment, students will implement the AI solution designed in their "
                "architecture report (Assessment 2). The deliverable includes a working end-to-end "
                "AI pipeline, a short demo video (max 8 minutes), and deployment documentation. "
                "Students are expected to apply MLOps tools (e.g., MLflow, Git, Docker, or similar), "
                "integrate data pipelines, model training, versioning, and deployment strategies. "
                "The demo must show the system in action and include a reflection on production "
                "readiness, performance, and maintenance considerations."
            ],
            "deliverables": [
                "Source code and environment files (e.g., requirements.txt, Dockerfile)",
                "Demo video showcasing pipeline functionality and tools used",
                "Deployment & operations documentation (markdown or PDF)",
                "README with usage instructions",
            ],
            "format": [],
            "rubric": [
                _rubric(
                    "Pipeline Implementation",
                    30,
                    _levels(
                        "Incomplete, poorly organized, or non-functional pipeline.",
                        "Basic pipeline implemented; some missing or hardcoded elements.",
                        "Mostly complete pipeline; minor modularity or reproducibility issues.",
                        "Complete, well-structured AI pipeline integrating data ingestion, "
                        "preprocessing, training, validation, and output generation. Modular and "
                        "reproducible.",
                    ),
                ),
                _rubric(
                    "Use of MLOps Tools",
                    20,
                    _levels(
                        "No evidence of MLOps tools; manual or ad hoc execution.",
                        "Limited tool use; partial automation or version control.",
                        "Good use of some tools; minor integration gaps.",
                        "Effective use of versioning, tracking, and automation tools (e.g., MLflow, "
                        "Git, CI/CD, Docker) for reproducible and scalable workflows.",
                    ),
                ),
                _rubric(
                    "Deployment & Documentation",
                    20,
                    _levels(
                        "Deployment not attempted or poorly documented.",
                        "Deployment approach described, but setup is incomplete or unclear.",
                        "Mostly clear deployment with some documentation gaps.",
                        "Solution is deployed or prepared for deployment with clear documentation of "
                        "setup, scalability, and maintenance.",
                    ),
                ),
                _rubric(
                    "Demo Video & Presentation",
                    20,
                    _levels(
                        "No demo or unclear, unfocused presentation.",
                        "Demo is basic or unclear in parts; limited reflection.",
                        "Clear demo with some minor pacing or clarity issues.",
                        "Demo is clear, well-paced, and effectively showcases the pipeline, tools, "
                        "and outcomes. Includes insightful commentary.",
                    ),
                ),
                _rubric(
                    "Reflection & Lessons Learned",
                    10,
                    _levels(
                        "No reflection or off-topic commentary.",
                        "Superficial reflection; limited learning analysis.",
                        "Basic reflection with some connection to design.",
                        "Provides insightful reflection on implementation challenges, trade-offs, "
                        "and performance. Links back to original design.",
                    ),
                ),
            ],
        },
        {
            "number": "A4",
            "title": "Communication and Reflection Video",
            "type": "Individual",
            "weight": 10,
            "total_marks": 100,
            "due": "Week 12",
            "lo_codes": ["LO5", "LO6"],
            "overview": [
                "Each student will record and submit an individual 5 to 7 minutes video "
                "presentation. The video should clearly explain the student's individual role in "
                "the AI solution project, the technical decisions they made, how they approached "
                "communication, and the key lessons learned. It should also include a critical "
                "reflection on any ethical and operational considerations they encountered during "
                "the solution development process."
            ],
            "deliverables": [],
            "format": [
                "Introduction: Briefly introduce yourself and the project context.",
                "Your Role: Describe your specific responsibilities and contributions to the AI "
                "project.",
                "Technical Decisions: Explain key technical decisions you made and why.",
                "Communication Approach: Reflect on how you coordinated and collaborated with "
                "others, even in a group setting.",
                "Ethical & Operational Insights: Discuss any ethical, security, or operational "
                "issues relevant to your contribution.",
                "Lessons Learned: Reflect on what you learned through the experience and how it has "
                "contributed to your personal and professional growth.",
            ],
            "rubric": [
                _rubric(
                    "Explanation of Individual Contribution",
                    25,
                    _levels(
                        "Contribution is vague, lacks clarity or ownership.",
                        "Mentions role and contributions, but with limited clarity or specificity.",
                        "Clearly describes personal contributions and technical decisions with good "
                        "rationale.",
                        "Provides a detailed, insightful account of specific technical tasks and "
                        "decisions. Demonstrates full ownership of individual role.",
                    ),
                ),
                _rubric(
                    "Reflection on Communication Approach",
                    20,
                    _levels(
                        "Minimal or no personal reflection on communication approach.",
                        "Some discussion of communication, but limited to generalities.",
                        "Describes communication experience with reasonable insight.",
                        "Offers a strong personal reflection on communication strategies, "
                        "challenges, and successes within the project context.",
                    ),
                ),
                _rubric(
                    "Ethical & Operational Considerations",
                    20,
                    _levels(
                        "Fails to address ethical or operational considerations.",
                        "Mentions ethical or operational elements without elaboration.",
                        "Identifies relevant issues with brief reflection on implications.",
                        "Thoughtfully analyzes ethical, fairness, or operational issues relevant to "
                        "their individual contribution.",
                    ),
                ),
                _rubric(
                    "Clarity, Structure, and Presentation Quality",
                    20,
                    _levels(
                        "Unclear, poorly structured, or difficult to follow.",
                        "Understandable but may lack structure, fluency, or confidence.",
                        "Generally clear and organized presentation with minor flaws.",
                        "Highly professional, well-structured, clear, and engaging delivery.",
                    ),
                ),
                _rubric(
                    "Critical Reflection and Personal Learning",
                    15,
                    _levels(
                        "No meaningful reflection or self-assessment evident.",
                        "Basic reflection with limited depth or insight.",
                        "Clear articulation of lessons learned and areas for improvement.",
                        "Deep and meaningful reflection on learning, personal growth, and skill "
                        "development.",
                    ),
                ),
            ],
        },
    ]


def demo_outline() -> dict:
    """The full MAAI 903 template, from subject details through section 12."""
    plos = [
        (
            "PLO1",
            "Evaluate organizational and societal challenges and formulate AI-driven strategies "
            "that align with business objectives, ethical standards, and regulatory frameworks.",
        ),
        (
            "PLO2",
            "Analyze real-world problems related to data, automation, and intelligence, and design "
            "practical AI solutions using modern machine learning, data engineering, and MLOps "
            "practices.",
        ),
        (
            "PLO3",
            "Analyze the suitability of traditional and modern AI models and architectures for "
            "different data types and industry applications.",
        ),
        (
            "PLO4",
            "Formulate and implement innovative, automated, and value-driven solutions across "
            "diverse industry sectors, using modern AI and transformative leadership concepts.",
        ),
        (
            "PLO5",
            "Conduct applied or research-based AI projects independently or collaboratively, "
            "demonstrating critical thinking, methodological rigor, and technical proficiency.",
        ),
        (
            "PLO6",
            "Demonstrate professional and interpersonal competencies by communicating technical "
            "concepts effectively, collaborating, and applying ethical reasoning and leadership in "
            "applied AI initiatives.",
        ),
    ]
    clos = [
        (
            "LO1",
            "Design end-to-end AI solution architectures that meet real-world business or societal "
            "needs.",
            ["PLO1", "PLO2", "PLO3", "PLO4", "PLO5"],
        ),
        (
            "LO2",
            "Implement reproducible and automated machine learning workflows using "
            "industry-standard MLOps tools and practices.",
            ["PLO2", "PLO3", "PLO4", "PLO5"],
        ),
        (
            "LO3",
            "Evaluate the scalability, reliability, and maintainability of AI solutions deployed in "
            "production environments.",
            ["PLO1", "PLO2", "PLO3", "PLO5"],
        ),
        (
            "LO4",
            "Apply CI/CD principles and versioning strategies for managing data, models, and "
            "pipelines in the AI lifecycle.",
            ["PLO2", "PLO3", "PLO4", "PLO5"],
        ),
        (
            "LO5",
            "Assess ethical, regulatory, and operational considerations in the deployment of AI "
            "systems at scale.",
            ["PLO1", "PLO4", "PLO6"],
        ),
        (
            "LO6",
            "Communicate solution design decisions and operational challenges effectively to "
            "technical and non-technical stakeholders.",
            ["PLO5", "PLO6"],
        ),
    ]
    weeks = [
        (
            1,
            "AI Systems Design Overview / Workshop: Analyzing Use Cases & Problem Scoping",
            ["LO1"],
            "Lecture (L)/ Workshop (W)",
            "F2F",
            "Workshop (F)",
        ),
        (
            2,
            "Solution Architecture & ML Lifecycle / Workshop: Building Solution Blueprints",
            ["LO1"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            3,
            "Data and Model Versioning / Workshop: Using DVC & Git for Tracking ML Assets",
            ["LO2", "LO4"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            4,
            "Reproducible Experimentation & Tracking / Workshop: Experiment Tracking with MLflow",
            ["LO2"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            5,
            "Model Deployment Techniques / Workshop: Serving Models via REST APIs and Containers",
            ["LO2", "LO3"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            6,
            "CI/CD for Machine Learning / Workshop: Building ML Pipelines using GitHub Actions / "
            "Jenkins",
            ["LO2", "LO4"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            7,
            "Monitoring & Retraining Strategies / Workshop: Logging, Drift Detection, and Feedback "
            "Loops",
            ["LO3"],
            "L/W",
            "F2F",
            "Workshop (F); Solution Architecture Report (S)",
        ),
        (
            8,
            "Scalability and Maintainability in Production / Workshop: Infrastructure Planning "
            "(e.g., Kubernetes, SageMaker)",
            ["LO3", "LO4"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            9,
            "MLOps Tools & Ecosystems / Workshop: Tool Stack Integration (MLflow, Kubeflow, "
            "Metaflow)",
            ["LO2", "LO3"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            10,
            "Governance, Risk, and Ethics in AI Operations / Workshop: Auditing AI Systems for "
            "Compliance and Fairness",
            ["LO5"],
            "L/W",
            "F2F",
            "Workshop (F)",
        ),
        (
            11,
            "Review & presentations / Projects presentations and Communicating AI Solutions to "
            "Stakeholders",
            ["LO6"],
            "-",
            "F2F",
            "Group Project (S); Communication & Reflection Video (S) / Week 12",
        ),
    ]
    readings = [
        "Burkov, Andriy. Machine learning engineering. Vol. 1. Montreal, QC, Canada: True Positive "
        "Incorporated, 2020.",
        "Huyen, Chip. Designing machine learning systems. O'Reilly Media, Inc., 2022.",
        "Osipov, Carl. MLOps Engineering at Scale. Manning Publications Co. LLC, 2022.",
        "Hapke, Hannes, and Catherine Nelson. Building machine learning pipelines. O'Reilly Media, "
        "2020.",
        "Gift, Noah, and Alfredo Deza. Practical MLOps. O'Reilly Media, Inc., 2021.",
    ]
    outcome_measures = [
        ("LO1", "Solution architecture report, group project"),
        ("LO2", "Workshops, group project"),
        ("LO3", "Workshops, solution architecture report, group project"),
        ("LO4", "Workshops, group project"),
        ("LO5", "Solution architecture report, reflection & communication video"),
        ("LO6", "Reflection & communication video, group project"),
    ]
    return {
        "basics": {
            "name": "AI Solutions Design & MLOps",
            "code": "MAAI 903",
            "section": "Autumn",
            "credit_points": 6,
            "year": 2026,
            "session": "Autumn",
            "duration": "11 weeks",
            "prerequisites": "MAAI 901, MAAI 902",
            "equivalent_subjects": "Nil",
            "delivery_mode": "F2F",
        },
        "lecture": {
            "day": "Thursday",
            "time": "18:00 \u2013 22:00",
            "location": "3.48-Classroom B",
            "educator_name": "Dr Patrick Mukala",
            "office": "3rd Floor in the New building",
            "email": "PATRICKMUKALA@UOWDUBAI.AC.AE",
            "consultation": (
                "WebEx/email/F2F. Wednesday: 9:00 \u2013 11:00; Thursday: 10:00 \u2013 12:00."
            ),
        },
        "description": (
            "This subject focuses on the practical aspects of building, deploying, and managing AI "
            "systems in production environments. Students will learn how to design scalable AI "
            "solutions, automate workflows using modern MLOps tools, and implement continuous "
            "integration and delivery pipelines. Emphasis is placed on reproducibility, model "
            "tracking, data versioning, and the ethical and regulatory dimensions of deploying AI "
            "at scale. By the end of the subject, students will be able to bridge the gap between "
            "model development and real-world operationalization, preparing them for technical "
            "leadership roles in AI implementation projects."
        ),
        "program": "Master of Applied Artificial Intelligence",
        "plos": [{"code": code, "text": text} for code, text in plos],
        "clos": [{"code": code, "text": text, "plos": mapped} for code, text, mapped in clos],
        "weeks": [
            {
                "week": week,
                "topic": topic,
                "lo_codes": los,
                "session_type": session,
                "delivery": delivery,
                "assessment_note": note,
            }
            for week, topic, los, session, delivery, note in weeks
        ],
        "readings": readings,
        "supporting_intro": SUPPORTING_INTRO,
        "supporting_access": SUPPORTING_ACCESS,
        "outcome_measures": [
            {"lo_code": code, "measures": measures} for code, measures in outcome_measures
        ],
        "assessment_tasks": _assessment_tasks(),
        "late_submission": LATE_SUBMISSION,
        "genai_intro": GENAI_INTRO,
        "genai": GENAI_POINTS,
        "grades": GRADES,
        "satisfactory": SATISFACTORY,
        "satisfactory_note": SATISFACTORY_NOTE,
        "policy_intro": POLICY_INTRO,
        "policy_documents": [{"title": title, "url": "", "text": ""} for title in POLICY_DOCUMENTS],
        "policies": [],
        "ssp": SSP,
        "academic_integrity": ACADEMIC_INTEGRITY,
        "attendance": ATTENDANCE,
        "supplementary": SUPPLEMENTARY,
        "lecture_capture": LECTURE_CAPTURE,
        "sustainability": SUSTAINABILITY,
        "source_materials": [],
    }


def empty_outline() -> dict:
    """A blank template. Every field is empty, so it never leaks the demo content."""
    return {
        "basics": dict.fromkeys(BASICS_FIELDS, ""),
        "lecture": dict.fromkeys(LECTURE_FIELDS, ""),
        "description": "",
        "program": "",
        "plos": [],
        "clos": [],
        "weeks": [],
        "readings": [],
        "supporting_intro": "",
        "supporting_access": "",
        "outcome_measures": [],
        "assessment_tasks": [],
        "late_submission": "",
        "genai_intro": "",
        "genai": [],
        "grades": [],
        "satisfactory": [],
        "satisfactory_note": "",
        "policy_intro": "",
        "policy_documents": [],
        "policies": [],
        "ssp": "",
        "academic_integrity": {},
        "attendance": "",
        "supplementary": "",
        "lecture_capture": "",
        "sustainability": "",
        "source_materials": [],
    }
