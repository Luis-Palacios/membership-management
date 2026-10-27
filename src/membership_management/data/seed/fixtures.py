"""Static Managua, Nicaragua data the seeders draw from."""

from typing import Literal, NamedTuple

from membership_management.data.small_groups.models import ReportSection

FEMALE_GIVEN_NAMES = [
    "María José", "Ana Lucía", "Karla Vanessa", "Fátima", "Yahoska", "Jessenia", "Martha Elena",
    "Rosa Argentina", "Claudia", "Gabriela", "Hazel", "Scarleth", "Ruth", "Sofía", "Valeria",
    "Johana", "Lesbia", "Xiomara", "Indira", "Daniela", "Carmen", "Mercedes", "Reyna Isabel",
    "Marbely", "Tania", "Heydi", "Belkis", "Norma", "Auxiliadora", "Eveling",
]  # fmt: skip

MALE_GIVEN_NAMES = [
    "José Luis", "Carlos Alberto", "Juan Carlos", "Francisco", "Marvin", "Lester", "Róger", "Erick",
    "Denis", "Álvaro", "Ernesto", "Wilmer", "Byron", "Kevin", "Josué", "Ricardo", "Douglas",
    "Manuel", "Óscar", "Jairo", "Henry", "Moisés", "Samuel", "Danilo", "Mauricio", "Bayardo",
    "Elvin", "Freddy", "Norlan", "Harold",
]  # fmt: skip

SURNAMES = [
    "López", "Gutiérrez", "Rocha", "Martínez", "Pérez", "García", "Hernández", "Rodríguez",
    "Mendoza", "Castillo", "Téllez", "Espinoza", "Aráuz", "Membreño", "Lacayo", "Blandón",
    "Zeledón", "Obando", "Úbeda", "Sevilla", "Lanzas", "Mairena", "Somarriba", "Báez", "Cerda",
    "Duarte", "Gaitán", "Jarquín", "Torrez", "Medrano", "Gómez", "Reyes", "Cruz", "Ruiz", "Vargas",
    "Sequeira", "Altamirano", "Morales", "Guevara", "Silva",
]  # fmt: skip

# Managua addresses are given from a landmark ("de ... 2 c. al lago, 1 c. arriba"): al lago = north,
# al sur = south, arriba = east, abajo = west; "c." = cuadras (blocks).
NEIGHBORHOOD_LANDMARKS: dict[str, list[str]] = {
    "Bolonia": ["Canal 2", "la iglesia El Carmen", "el parque de Bolonia"],
    "Altamira": ["donde fue la Vicky", "la farmacia Altamira", "el colegio Teresiano"],
    "Villa Fontana": ["el Club Terraza", "la entrada principal", "la gasolinera"],
    "Bello Horizonte": ["la rotonda de Bello Horizonte", "el parque central", "la iglesia católica"],
    "Las Colinas": ["la entrada principal", "la pulpería La Esperanza", "el colegio"],
    "Ciudad Jardín": ["el mercadito", "la iglesia Santa Faz", "la farmacia"],
    "Linda Vista": ["el semáforo", "la iglesia de Linda Vista", "el parque"],
    "Monseñor Lezcano": ["la iglesia", "el estadio", "el parque Las Piedrecitas"],
    "Altagracia": ["el parque Altagracia", "la iglesia de Altagracia", "el colegio"],
    "Villa Libertad": ["el centro de salud", "la parada de buses", "la terminal"],
    "Las Brisas": ["el puente", "el parque", "la pulpería Doña Chepita"],
    "Reparto San Juan": ["la UCA", "el gimnasio", "la farmacia"],
    "Sabana Grande": ["la rotonda", "el empalme", "la iglesia"],
    "Colonia Centroamérica": ["el mercadito", "la iglesia Fátima", "el parque"],
}  # fmt: skip

DIRECTIONS_NS = ["al lago", "al sur"]
DIRECTIONS_EW = ["arriba", "abajo"]
BLOCKS = ["1/2", "1", "2", "3"]

# Nicaraguan mobile numbers: +505 then 8 digits starting with 5, 7 or 8.
MOBILE_PREFIXES = ["5", "7", "8"]

SMALL_GROUPS = [
    # (name, neighborhood it meets in, ISO weekday); neighborhoods are keys of NEIGHBORHOOD_LANDMARKS.
    ("GP - #1", "Bolonia", 2),
    ("GP - #2", "Altamira", 3),
    ("GP - #3", "Villa Fontana", 5),
    ("GP - #4", "Bello Horizonte", 4),
    ("GP - #5", "Las Colinas", 6),
]

GROUP_PRAYER_REQUESTS = [
    "Por la salud de la mamá de un hermano, hospitalizada en el Hospital Manolo Morales.",
    "Por trabajo para dos hermanos que están desempleados.",
    "Por los jóvenes del grupo que están en exámenes de la universidad.",
    "Por la restauración de un matrimonio del grupo.",
    "Por provisión para los gastos escolares de los niños.",
    "Por una hermana que viaja a Costa Rica la próxima semana.",
    "Por la salud de un hermano que sigue con dengue.",
    "Por los vecinos que invitamos y aún no han venido.",
]

GROUP_PRAISE_REPORTS = [
    "Una hermana consiguió trabajo esta semana.",
    "Dios sanó al hijo de un hermano que estaba con fiebre.",
    "Dos vecinos nos visitaron por primera vez.",
    "Un hermano terminó su tratamiento con buenos resultados.",
    "Se reconcilió una familia del grupo.",
    "Pudimos ayudar con víveres a una familia del barrio.",
]

GROUP_DISCUSSIONS = [
    "Se habló de organizar una visita a los hermanos que han faltado.",
    "El grupo quiere apoyar la actividad de evangelismo del próximo mes.",
    "Proponen rotar la casa donde se reúnen.",
    "Varios preguntaron por el próximo bautismo.",
    "Se planificó un convivio para fin de mes.",
]

# Items that tag someone; {p} is where the person goes.
TAGGED_PRAYER_REQUESTS = [
    "Por {p}, que está buscando trabajo.",
    "Por la salud de la mamá de {p}.",
    "Por {p} y su familia, que se mudan este mes.",
    "Por {p}, que tiene exámenes esta semana.",
    "Por el viaje de {p} a Estelí.",
    "Por {p}, que está pasando por un tiempo difícil en casa.",
]

TAGGED_PRAISE_REPORTS = [
    "{p} consiguió trabajo esta semana.",
    "Dios sanó a {p} de la fiebre.",
    "{p} trajo a un vecino por primera vez.",
    "{p} terminó su tratamiento con buenos resultados.",
]

TAGGED_DISCUSSIONS = [
    "{p} pidió hablar con un anciano sobre el bautismo.",
    "Visitar a {p}, que lleva dos semanas sin venir.",
    "{p} quiere servir en el ministerio de niños.",
]

NOT_HELD_REASONS = [
    "Lluvia fuerte; casi nadie pudo llegar.",
    "Feriado; el grupo acordó no reunirse.",
    "El líder estaba de viaje y no hubo quién dirigiera.",
    "Corte de energía en la zona.",
    "Última semana del mes: sin reunión.",
    None,
]

ABSENCE_OBSERVATIONS = [
    "Avisó que estaba enfermo; se le llamó para orar.",
    "Turno de trabajo; dijo que vendrá la otra semana.",
    "Viajó a Matagalpa por asuntos familiares.",
    "No respondió llamadas; conviene visitarlo.",
    "Cuidando a un familiar enfermo.",
]


# Report conversations: threads on a person's attendance row, or on a report section when `section` is
# set. Each thread is one report (`group`: the n-th seeded group, `report`: how many held reports back
# from the newest; for a section, the first from there with text in it) and its comments in order.
class SeedComment(NamedTuple):
    side: Literal["elders", "leaders"]
    body: str
    # The text it had before an edit, if it was edited.
    edited_from: str | None = None
    deleted: bool = False


class SeedThread(NamedTuple):
    group: int
    report: int
    comments: list[SeedComment]
    # "elders" / "leaders": who resolved it; None = still open.
    resolved_by: Literal["elders", "leaders"] | None = None
    section: ReportSection | None = None


CONVERSATION_THREADS = [
    # Waiting for the leaders.
    SeedThread(
        group=0,
        report=0,
        comments=[
            SeedComment("elders", "Faltó dos semanas seguidas. ¿Saben si pasa algo con él o con su familia?"),
        ],
    ),
    # Waiting for the elders.
    SeedThread(
        group=1,
        report=0,
        comments=[
            SeedComment("elders", "Vi que no vino a la iglesia el domingo. ¿Lo pudieron contactar?"),
            SeedComment(
                "leaders",
                "Lo llamé ayer. Trabaja turnos de noche y no puede venir. Le dije que oraremos por él.",
            ),
        ],
    ),
    # A leader started it; waiting for the elders. The comment was edited.
    SeedThread(
        group=2,
        report=0,
        comments=[
            SeedComment(
                "leaders",
                "Esta persona perdió su trabajo y necesita orientación. ¿Quién puede visitarla con nosotros?",
                edited_from="Esta persona perdió su trabajo. ¿Quién puede visitarla?",
            ),
        ],
    ),
    # Resolved by an elder.
    SeedThread(
        group=3,
        report=0,
        resolved_by="elders",
        comments=[
            SeedComment("elders", "Notamos que lleva tres reuniones sin asistir. ¿Ha dicho algo?"),
            SeedComment("leaders", "Se mudó de casa y le queda lejos. Ya quedamos en pasar a recogerlo."),
            SeedComment("elders", "Perfecto, gracias. Lo damos por atendido."),
        ],
    ),
    # A deleted reply, then another one.
    SeedThread(
        group=4,
        report=0,
        comments=[
            SeedComment("elders", "¿Cómo va el seguimiento con esta familia?"),
            SeedComment("leaders", "Escribí algo equivocado aquí, perdón.", deleted=True),
            SeedComment(
                "leaders", "Los visitamos el sábado. Están animados y quieren volver a las reuniones."
            ),
        ],
    ),
    # An older report, resolved by a leader.
    SeedThread(
        group=0,
        report=3,
        resolved_by="leaders",
        comments=[
            SeedComment("elders", "Pregunta sobre el hermano que estuvo enfermo: ¿ya se recuperó?"),
            SeedComment("leaders", "Sí, ya está de alta y vino la semana pasada. Todo bien."),
        ],
    ),
    # An older report, still open, the elders spoke last.
    SeedThread(
        group=1,
        report=2,
        comments=[
            SeedComment("leaders", "Ella pidió oración por su mamá, que sigue hospitalizada."),
            SeedComment("elders", "Gracias por avisar. Un anciano la llamará esta semana."),
        ],
    ),
    # Section threads (prayer & follow-up). Follow-up started by an elder, the leader answered last.
    SeedThread(
        group=1,
        report=0,
        section=ReportSection.FOLLOW_UP,
        comments=[
            SeedComment(
                "elders", "¿Quieren que un anciano los acompañe en la visita? Díganme qué día les sirve."
            ),
            SeedComment("leaders", "Sí, por favor. El sábado en la tarde nos queda bien a todos."),
        ],
    ),
    # A prayer request, resolved by an elder.
    SeedThread(
        group=0,
        report=0,
        section=ReportSection.PRAYER,
        resolved_by="elders",
        comments=[
            SeedComment("elders", "Lo incluimos en la oración del domingo. ¿Hay alguna novedad?"),
            SeedComment("leaders", "Gracias. Ya le dieron trabajo; quedó contestada."),
        ],
    ),
    # Praise with a single comment, waiting for the leaders.
    SeedThread(
        group=3,
        report=0,
        section=ReportSection.PRAISE,
        comments=[
            SeedComment(
                "elders", "¡Gloria a Dios! Compártanlo también el domingo en el anuncio de testimonios."
            ),
        ],
    ),
]
