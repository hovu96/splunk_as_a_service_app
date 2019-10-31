const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "splunkjs/ready!"
],
    function (
        $,
        _
    ) {

        const addButton = $("<div></div>");
        $(".dashboard-view-controls").append(addButton);
        addButton.append($("<button class=\"btn btn-primary action-button\">Create Stack</button>").click(async function () {
            window.location.href = 'stack_create';
        }))

    });
