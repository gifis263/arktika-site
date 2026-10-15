document.addEventListener('DOMContentLoaded', function () {
    fetch('/api/stats', { headers: { Accept: 'application/json' } })
        .then(function (response) { if (!response.ok) throw new Error('stats unavailable'); return response.json(); })
        .then(function (stats) {
            const values = { participantCounter: stats.participants, statParticipants: stats.participants, statProjects: stats.projects, statLessons: stats.lessons };
            Object.keys(values).forEach(function (id) {
                const el = document.getElementById(id);
                if (el && Number.isFinite(Number(values[id]))) el.textContent = String(values[id]);
            });
        })
        .catch(function (error) {
            document.querySelectorAll('#participantCounter, #statParticipants, #statProjects, #statLessons').forEach(function (el) { el.textContent = '—'; });
            console.warn('Статистика недоступна:', error);
        });
    document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
        anchor.addEventListener('click', function (event) {
            const target = document.querySelector(this.getAttribute('href'));
            if (target) { event.preventDefault(); target.scrollIntoView({ behavior: 'smooth' }); }
        });
    });
});
