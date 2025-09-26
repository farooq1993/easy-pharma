// Toggle sidebar collapse/expand
        document.getElementById('sidebarToggle').addEventListener('click', function() {
            const sidebar = document.getElementById('sidebarMenu');
            const content = document.getElementById('mainContent');
            
            sidebar.classList.toggle('collapsed');
            content.classList.toggle('expanded');
            
            // Change icon based on state
            const icon = this.querySelector('i');
            if (sidebar.classList.contains('collapsed')) {
                icon.classList.remove('bi-list');
                icon.classList.add('bi-chevron-right');
            } else {
                icon.classList.remove('bi-chevron-right');
                icon.classList.add('bi-list');
            }
        });
        
        // Close collapsed submenus when clicking elsewhere
        document.addEventListener('click', function(event) {
            if (!event.target.matches('.nav-link')) {
                const openCollapses = document.querySelectorAll('.collapse.show');
                openCollapses.forEach(function(collapse) {
                    const bsCollapse = new bootstrap.Collapse(collapse, {
                        toggle: false
                    });
                    bsCollapse.hide();
                });
            }
        });