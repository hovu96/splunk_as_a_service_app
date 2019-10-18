import os
import fix_path


def main():
    cluster_field_prefix = "SAAS_CLUSTER_FIELD_"
    cluster_fields = {}
    #self.fail("os.environ: %s" % os.environ)
    for k, v in os.environ.items():
        if k.startswith(cluster_field_prefix):
            name = k[len(cluster_field_prefix):]
            cluster_fields[name] = v
    print ("%s" % cluster_fields)
    #raise Exception("cluster_fields: %s" % cluster_fields)


if __name__ == "__main__":
    main()
