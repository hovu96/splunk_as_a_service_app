
require([
    "jquery",
    "splunkjs/ready!"
],
    function ($, _) {

        const addButton = $(`
            <button class="btn btn-primary action-button">
                Add Cluster
            </button>
        `);
        addButton.click(async function () {
            window.location.href = 'cluster';
        })
        $(".dashboard-view-controls").append(addButton);
    }
);