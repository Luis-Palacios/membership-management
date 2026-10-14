"""Static Managua, Nicaragua data the seeders draw from."""

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

ABSENCE_OBSERVATIONS = [
    "Avisó que estaba enfermo; se le llamó para orar.",
    "Turno de trabajo; dijo que vendrá la otra semana.",
    "Viajó a Matagalpa por asuntos familiares.",
    "No respondió llamadas; conviene visitarlo.",
    "Cuidando a un familiar enfermo.",
]
