
require([
    "jquery",
    "splunkjs/ready!"
],
    function (
        $,
        _
    ) {

        const addButton = $(`
            <button class="btn btn-primary action-button">
                Create Stack
            </button>
        `);
        addButton.click(async function () {
            window.location.href = 'stack_create';
        })
        $(".dashboard-view-controls").append(addButton);

    });
