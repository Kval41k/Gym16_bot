
        const adminParams = new URLSearchParams(location.search);
        const adminId = Number(adminParams.get('admin_id'));
        const authTs = Number(adminParams.get('ts'));
        const authSign = adminParams.get('sign') || '';

        function filterUsers() {
            const query = document.getElementById("searchInput").value.toLowerCase();
            const rows = document.querySelectorAll("#usersTable tbody tr");
            rows.forEach(r => {
                const text = r.innerText.toLowerCase();
                r.style.display = text.includes(query) ? "" : "none";
            });
        }

        async function toggleBan(userId, setBanned) {
            const action = setBanned ? "заблокировать" : "разблокировать";
            if (!confirm(`Вы действительно хотите ${action} этого пользователя?`)) return;

            try {
                const res = await fetch(`/api/admin/users/${userId}/ban`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ admin_id: adminId, ts: authTs, sign: authSign, is_banned: setBanned })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Ошибка запроса");

                const statusEl = document.getElementById(`status-${userId}`);
                const actionEl = document.getElementById(`action-${userId}`);
                const row = document.querySelector(`tr[data-user-id="${userId}"]`);

                if (setBanned) {
                    statusEl.innerHTML = '<span class="badge badge-banned">🚫 Заблокирован</span>';
                    actionEl.innerHTML = `<button data-ban-id="${userId}" data-ban-value="false" class="btn btn-unban">✅ Разбанить</button>`;
                    row?.classList.add("row-banned");
                } else {
                    statusEl.innerHTML = '<span class="badge badge-active">🟢 Активен</span>';
                    actionEl.innerHTML = `<button data-ban-id="${userId}" data-ban-value="true" class="btn btn-ban">🚫 Забанить</button>`;
                    row?.classList.remove("row-banned");
                }
            } catch (err) {
                alert("Ошибка: " + err.message);
            }
        }

document.addEventListener('input',e=>{if(e.target.id==='searchInput')filterUsers();});
document.addEventListener('click',e=>{const b=e.target.closest('[data-ban-id]');if(b)toggleBan(Number(b.dataset.banId),b.dataset.banValue==='true');});
